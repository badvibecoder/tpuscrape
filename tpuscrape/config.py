"""Configuration loader with sane defaults."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "base_url": "https://www.techpowerup.com",
    "seed_url": "https://www.techpowerup.com/gpu-specs/geforce-rtx-5090.c4216",
    "url_feed_file": "scripts/seed_urls.txt",
    "output_dir": "data",
    "state_dir": "state",
    "profile_dir": ".browser-profile",
    "browser": {
        "chrome_binary": "/usr/bin/google-chrome-stable",
        "port": 9222,
        "headless": False,
        "window_size": [1440, 900],
    },
    "timing": {
        "delay_min": 2.0,
        "delay_max": 6.0,
        "nav_timeout_ms": 60000,
        "challenge_wait_seconds": 60,
        "human_wait_seconds": 900,
        "discover_delay_min": 1.0,
        "discover_delay_max": 2.0,
    },
    "scrape": {
        "include_description": False,
        "include_images": False,
        "keep_html": False,
    },
    "status": {"host": "127.0.0.1", "port": 8080},
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict):
        self.data = data

    def get(self, dotted: str, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, dotted: str) -> Path:
        """Resolve a path-like config value relative to the project root."""
        val = self.get(dotted)
        p = Path(val)
        return p if p.is_absolute() else ROOT / p

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        data = _merge(DEFAULTS, {})
        cfg_path = Path(path) if path else ROOT / "config.yaml"
        if cfg_path.exists():
            with cfg_path.open("r", encoding="utf-8") as fh:
                overrides = yaml.safe_load(fh) or {}
            data = _merge(data, overrides)
        return cls(data)


def load_config(path: Path | str | None = None) -> Config:
    return Config.load(path)
