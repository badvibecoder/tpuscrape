"""Thread-safe shared runtime state between the scraper loop and the status API."""
from __future__ import annotations

import threading
import time
from collections import deque


class RuntimeState:
    def __init__(self):
        self._lock = threading.Lock()
        self.paused = False
        self.current: dict | None = None
        self.blocked = False
        self.blocked_url: str = ""
        self.blocked_id: str = ""
        self.started_at = time.time()
        self.events: deque[str] = deque(maxlen=200)
        self.last_error: str = ""
        self.scraped_count = 0

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        with self._lock:
            self.events.appendleft(line)
        print(line, flush=True)

    def set_current(self, gpu: dict | None):
        with self._lock:
            self.current = dict(gpu) if gpu else None

    def set_blocked(self, gpu_id: str, url: str):
        with self._lock:
            self.blocked = True
            self.blocked_id = gpu_id
            self.blocked_url = url

    def clear_blocked(self):
        with self._lock:
            self.blocked = False
            self.blocked_id = ""
            self.blocked_url = ""

    def set_paused(self, paused: bool):
        with self._lock:
            self.paused = paused

    def is_paused(self) -> bool:
        with self._lock:
            return self.paused

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "paused": self.paused,
                "blocked": self.blocked,
                "blocked_id": self.blocked_id,
                "blocked_url": self.blocked_url,
                "current": self.current,
                "uptime_s": int(time.time() - self.started_at),
                "scraped_count": self.scraped_count,
                "last_error": self.last_error,
                "events": list(self.events)[:50],
            }
