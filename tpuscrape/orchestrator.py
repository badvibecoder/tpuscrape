"""Main scraping loop: browser + parser + store + queue, with human-in-the-loop challenge handling."""
from __future__ import annotations

import random
import time

from .browser import BrowserSession
from .challenge import detect, wait_for_resolution
from .config import Config
from .media import download_images
from .parser import parse_html
from .frontier import Queue, slugify
from .runtime import RuntimeState
from .store import Store


def build_summary(parsed: dict) -> dict:
    s = {t["label"]: t["value"] for t in parsed.get("top_specs", [])}
    for pairs in parsed.get("sections", {}).values():
        for pair in pairs:
            if pair["label"] in ("Architecture", "Foundry", "Release Date", "Launch Price"):
                s[pair["label"]] = pair["value"]
    return s


class Scraper:
    def __init__(self, config: Config, store: Store, queue: Queue, runtime: RuntimeState):
        self.config = config
        self.store = store
        self.queue = queue
        self.runtime = runtime
        self.human_wait = config.get("timing.human_wait_seconds", 600)

    def run(
        self,
        max_gpus: int | None = None,
        stop_when_empty: bool = False,
        discover: bool = False,
        discover_only: bool = False,
        delay_min: float | None = None,
        delay_max: float | None = None,
        include_description: bool | None = None,
        include_images: bool | None = None,
        keep_html: bool | None = None,
    ):
        self.queue.seed()
        self.queue.reload_feed()
        self.runtime.log("starting scraper")

        # Random backoff between GPU page fetches. CLI overrides, else config (default 2–6s).
        cfg_lo = self.config.get("timing.delay_min", 2.0)
        cfg_hi = self.config.get("timing.delay_max", 6.0)
        d_lo = delay_min if delay_min is not None else cfg_lo
        d_hi = delay_max if delay_max is not None else cfg_hi
        if delay_min is not None and delay_max is None:
            d_hi = max(d_hi, d_lo)  # ensure max >= min
        if delay_max is not None and delay_min is None:
            d_lo = min(d_lo, d_hi)  # ensure min <= max
        self._delay_lo, self._delay_hi = min(d_lo, d_hi), max(d_lo, d_hi)
        self.runtime.log(f"delay between fetches: {self._delay_lo:.1f}–{self._delay_hi:.1f}s")

        # Opt-in content flags (default off). CLI overrides, else config.
        self.include_description = (
            include_description
            if include_description is not None
            else self.config.get("scrape.include_description", False)
        )
        self.include_images = (
            include_images if include_images is not None else self.config.get("scrape.include_images", False)
        )
        self.keep_html = keep_html if keep_html is not None else self.config.get("scrape.keep_html", False)

        session = BrowserSession(self.config)
        session.start()
        self.runtime.log("browser started (headed Chrome over CDP)")

        try:
            if discover or discover_only:
                self._discover(session)
            if discover_only:
                self.runtime.log("discovery-only mode complete")
                return

            done = 0
            while True:
                if self.runtime.is_paused():
                    time.sleep(1)
                    continue

                self.queue.reload_feed()
                gpu = self.queue.next_random()
                if gpu is None:
                    if stop_when_empty:
                        self.runtime.log("queue empty — stopping (--stop-when-empty)")
                        break
                    self.runtime.log("queue empty — idle; add URLs via feed file or status page")
                    time.sleep(3)
                    continue

                self.runtime.set_current(gpu)
                self.store.set_status(gpu["id"], "in_progress")
                self.store.bump_attempt(gpu["id"])
                self.runtime.log(f"scraping {gpu['id']} ({gpu['name'] or gpu['url']})")

                ok = self._scrape_one(session, gpu)
                if ok:
                    done += 1
                    self.runtime.scraped_count += 1
                self.runtime.set_current(None)

                # polite randomized delay
                time.sleep(random.uniform(self._delay_lo, self._delay_hi))
                if max_gpus is not None and done >= max_gpus:
                    self.runtime.log(f"reached --max {max_gpus}; stopping")
                    break
        finally:
            session.close()
            self.store.write_index()
            self.runtime.log("scraper stopped")

    def _discover(self, session: BrowserSession) -> int:
        from .discover import discover

        n = discover(session, self.config, self.queue, self.runtime)
        self.store.write_index()
        return n

    # -- single GPU ----------------------------------------------------------
    def _scrape_one(self, session: BrowserSession, gpu: dict) -> bool:
        page = None
        try:
            page = session.new_page()
            if not self._load_real_page(page, gpu):
                return False

            # Real page is here.
            page.wait_for_selector("h1.gpudb-name", timeout=30000)
            if page.locator("section.gpudb-relative-performance").count() > 0:
                try:
                    page.wait_for_selector(".gpudb-relative-performance-entry", timeout=10000)
                except Exception:
                    pass
            time.sleep(0.5)

            final_url = page.url
            html = page.content()
            parsed = parse_html(html, final_url)

            # Canonicalize id/slug/name/url.
            gpu_id = parsed.get("id") or gpu["id"]
            name = parsed.get("name") or gpu["name"]
            slug = parsed.get("slug") or slugify(name) or f"c{gpu_id}"
            self.store.upsert_gpu(
                gpu_id=gpu_id,
                name=name,
                url=final_url,
                slug=slug,
                source=gpu.get("source", "seed"),
            )

            folder = self.store.gpu_folder(slug)

            # Opt-in content (editorial description / images / raw HTML) — off by default.
            if not self.include_description:
                parsed.pop("description", None)
            image_count = 0
            if self.include_images:
                images = download_images(parsed.get("images", []), folder / "images")
                parsed["images"] = images
                image_count = len(images)
            else:
                parsed.pop("images", None)
            parsed["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            if self.keep_html:
                self.store.write_raw_html(slug, html)
            self.store.write_spec(slug, parsed)

            self.queue.add_relative_entries(parsed.get("relative_performance", []))
            self.store.set_status(
                gpu_id, "done", scraped_at=parsed["scraped_at"], summary=build_summary(parsed)
            )
            self.store.write_index()
            self.runtime.log(
                f"done {name} ({gpu_id}): {len(parsed['relative_performance'])} perf entries, "
                f"{len(parsed['boards'].get('boards', []))} boards, {image_count} images"
            )
            return True
        except Exception as exc:
            gpu_id = gpu.get("id", "?")
            self.runtime.last_error = str(exc)
            self.store.set_status(gpu_id, "failed", error=str(exc))
            self.runtime.log(f"failed {gpu_id}: {exc}")
            return False
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

    def _load_real_page(self, page, gpu: dict) -> bool:
        """Navigate to the GPU URL and get past the firewall challenge.

        Returns True when the real page is loaded; False if abandoned/timed out.
        """
        url = gpu["url"]
        gpu_id = gpu["id"]
        nav_timeout = self.config.get("timing.nav_timeout_ms", 60000)
        challenge_wait = self.config.get("timing.challenge_wait_seconds", 60)

        page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
        resolved, reason = wait_for_resolution(page, timeout_seconds=challenge_wait)

        if resolved:
            return True

        # Needs a human. Mark blocked and wait, polling for resolution or abort.
        self.store.set_status(gpu_id, "blocked", error=reason)
        self.runtime.set_blocked(gpu_id, page.url)
        self.runtime.log(f"⚠ challenge needs human: {page.url} ({reason})")

        deadline = time.time() + self.human_wait
        while time.time() < deadline:
            if detect(page) is None:
                self.runtime.clear_blocked()
                self.runtime.log(f"challenge solved by human: {gpu_id}")
                return True
            if not self.runtime.snapshot()["blocked"]:
                self.runtime.log(f"blocked scrape abandoned by user: {gpu_id}")
                return False
            time.sleep(2)

        self.runtime.clear_blocked()
        self.runtime.log(f"challenge wait timed out for {gpu_id}; will retry later")
        return False
