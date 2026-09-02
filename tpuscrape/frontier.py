"""Frontier management: seed URL, relative-performance links, and a URL feed file."""
from __future__ import annotations

import re
from pathlib import Path

from .config import Config
from .store import Store

_ID_RE = re.compile(r"\.c(\d+)")
_SLUG_RE = re.compile(r"gpu-specs/([a-z0-9-]+)\.c\d+")


def extract_id(url: str) -> str:
    m = _ID_RE.search(url)
    return m.group(1) if m else ""


def absolute_url(base: str, href: str) -> str:
    if href.startswith("http"):
        return href
    return base.rstrip("/") + "/" + href.lstrip("/")


def slug_from_url(url: str) -> str:
    m = _SLUG_RE.search(url)
    return m.group(1) if m else ""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class Queue:
    def __init__(self, config: Config, store: Store):
        self.config = config
        self.store = store
        self.base = config.get("base_url", "https://www.techpowerup.com").rstrip("/")
        self.feed_path: Path = config.path("url_feed_file")
        self.feed_path.parent.mkdir(parents=True, exist_ok=True)
        self.feed_path.touch(exist_ok=True)
        self._feed_mtime = 0.0

    def seed(self):
        """Add the configured seed URL if not present."""
        seed = self.config.get("seed_url")
        if not seed:
            return
        self.add_url(seed, source="seed")

    def add_url(self, url: str, source: str = "feed", name: str = ""):
        gpu_id = extract_id(url)
        if not gpu_id:
            return
        if self.store.has(gpu_id):
            return
        self.store.upsert_gpu(
            gpu_id=gpu_id,
            name=name or "",
            url=absolute_url(self.base, url) if url.startswith("/") else url,
            slug=slug_from_url(url),
            source=source,
        )

    def add_relative_entries(self, entries: list[dict]):
        """Add GPUs discovered in a relative-performance chart."""
        for e in entries:
            if e.get("is_primary"):
                continue
            href = e.get("href")
            if not href:
                continue
            gpu_id = extract_id(href)
            if not gpu_id or self.store.has(gpu_id):
                continue
            self.store.upsert_gpu(
                gpu_id=gpu_id,
                name=e.get("name") or e.get("title") or "",
                url=absolute_url(self.base, href),
                slug="",
                source="perf_list",
            )

    def reload_feed(self):
        """Read the URL feed file and add any new URLs."""
        try:
            mtime = self.feed_path.stat().st_mtime
        except FileNotFoundError:
            return 0
        if mtime == self._feed_mtime:
            return 0
        self._feed_mtime = mtime
        added = 0
        for line in self.feed_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "gpu-specs/" in line:
                before = self.store.has(extract_id(line))
                self.add_url(line, source="feed")
                if not before and self.store.has(extract_id(line)):
                    added += 1
        return added

    def next_random(self) -> dict | None:
        return self.store.random_pending()
