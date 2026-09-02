"""Download GPU images (direct CDN fetches, no firewall)."""
from __future__ import annotations

import re
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s or "image"


def _ext(url: str) -> str:
    return Path(url.split("?")[0]).suffix or ".jpg"


def download_images(images: list[dict], folder: Path) -> list[dict]:
    """Download the `large_url` for each image into `folder`; return enriched list."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    seen: set[str] = set()
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30) as client:
        for img in images:
            url = img.get("large_url") or img.get("thumb_url") or ""
            if not url:
                continue
            label = img.get("label") or "image"
            base = _slug(label)
            filename = f"{base}{_ext(url)}"
            # De-duplicate labels
            if filename in seen:
                filename = f"{base}-{len(seen)}{_ext(url)}"
            seen.add(filename)
            dest = folder / filename
            local = None
            try:
                resp = client.get(url)
                if resp.status_code == 200 and resp.content:
                    dest.write_bytes(resp.content)
                    local = dest.name
                else:
                    local = None
            except Exception:
                local = None
            out.append(
                {
                    "label": label,
                    "url": url,
                    "thumb_url": img.get("thumb_url", ""),
                    "file": local,
                }
            )
    return out
