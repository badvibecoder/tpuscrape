#!/usr/bin/env python3
"""Fetch a single GPU page in the real browser and dump the DOM for inspection.

Usage:
    .venv/bin/python scripts/fetch_one.py [url]

If no url is given, the configured seed_url is used.  Output (HTML, screenshot,
and a JSON summary) is written under `_inspect/`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tpuscrape.browser import BrowserSession  # noqa: E402
from tpuscrape.challenge import detect, wait_for_resolution  # noqa: E402
from tpuscrape.config import load_config  # noqa: E402


def slugify(url: str) -> str:
    m = re.search(r"gpu-specs/([a-z0-9-]+)\.c\d+", url)
    if m:
        return m.group(1)
    return re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")


def main() -> int:
    cfg = load_config()
    url = sys.argv[1] if len(sys.argv) > 1 else cfg.get("seed_url")
    out_dir = ROOT / "_inspect"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(url)

    session = BrowserSession(cfg)
    session.start()
    page = session.new_page()

    try:
        print(f"[fetch] navigating to {url}", flush=True)
        page.goto(url, wait_until="domcontentloaded", timeout=cfg.get("timing.nav_timeout_ms"))
        print("[fetch] waiting for firewall challenge to resolve...", flush=True)
        resolved, reason = wait_for_resolution(
            page, timeout_seconds=cfg.get("timing.challenge_wait_seconds", 60)
        )

        title = page.title()
        h1 = page.locator("h1").first.inner_text() if page.locator("h1").count() else "(no h1)"
        final_url = page.url

        summary = {
            "requested": url,
            "final_url": final_url,
            "title": title,
            "h1": h1,
            "challenge_resolved": resolved,
            "challenge_reason": reason,
        }

        html = page.content()
        html_path = out_dir / f"{slug}.html"
        html_path.write_text(html, encoding="utf-8")
        shot_path = out_dir / f"{slug}.png"
        page.screenshot(path=str(shot_path), full_page=False)
        summary_path = out_dir / f"{slug}.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print(json.dumps(summary, indent=2), flush=True)
        print(f"[fetch] saved {html_path}", flush=True)
        print(f"[fetch] saved {shot_path}", flush=True)
        return 0 if resolved else 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
