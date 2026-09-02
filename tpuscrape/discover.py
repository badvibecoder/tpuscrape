"""Architecture-based discovery: enumerate every architecture and enqueue all GPUs.

The upstream GPU database index (`/gpu-specs/`) supports an `architecture` filter.
Selecting a filter issues `GET /gpu-specs/?<query>&ajax`, which returns JSON of the
form `{"list": "<html>", "dropdown": "<html>", "filters": "<html>"}`.  The filter
URLs are lightly obfuscated (base64 + reversed) to deter bots; we decode them.

Flow:
  1. `?architecture=&ajax`  -> `filters` contains the full architecture dropdown
     (105 entries, each "Name (count)").
  2. For each architecture, paginate `?architecture=<value>&p=<n>&ajax` and harvest
     every `/gpu-specs/<slug>.c<id>` link.
  3. Feed each link into the shared queue (deduplicated by numeric GPU id).
"""
from __future__ import annotations

import base64
import math
import random
import re
import time

from bs4 import BeautifulSoup

GPU_LINK_RE = re.compile(r"gpu-specs/([a-z0-9-]+)\.c(\d+)")


def decode_filter_url(data_url: str) -> str:
    """Decode an obfuscated `#<base64(reversed(query))>` data-url back to its query."""
    if not data_url or not data_url.startswith("#"):
        return ""
    try:
        raw = base64.b64decode(data_url[1:]).decode("utf-8", "replace")
        return raw[::-1]
    except Exception:
        return ""


def parse_architectures(filters_html: str) -> list[dict]:
    soup = BeautifulSoup(filters_html, "lxml")
    archs: list[dict] = []
    for opt in soup.select("option[data-url]"):
        query = decode_filter_url(opt.get("data-url", ""))
        if "architecture=" not in query:
            continue
        text = opt.get_text(strip=True)
        m = re.search(r"^(.*?)\s*\((\d+)\)\s*$", text)
        name = m.group(1) if m else text
        count = int(m.group(2)) if m else None
        vm = re.search(r"architecture=([^&]*)", query)
        archs.append({"name": name, "count": count, "value": vm.group(1) if vm else ""})
    return archs


def parse_gpu_links(list_html: str) -> list[dict]:
    """Extract unique GPU card links from a `#list` fragment."""
    soup = BeautifulSoup(list_html, "lxml")
    found: dict[str, dict] = {}
    for a in soup.select("#list a[href]"):
        href = a.get("href", "")
        m = GPU_LINK_RE.search(href)
        if not m:
            continue
        gpu_id = m.group(2)
        name = a.get_text(strip=True)
        # Prefer the first non-empty name for a given id (rows have duplicate links).
        if gpu_id not in found or (name and not found[gpu_id]["name"]):
            found[gpu_id] = {"id": gpu_id, "name": name, "url": href}
    return list(found.values())


def _json_or_none(resp) -> dict | None:
    try:
        if getattr(resp, "status", 200) != 200:
            return None
        return resp.json()
    except Exception:
        return None


def discover(session, config, queue, runtime) -> int:
    """Enumerate all architectures and enqueue their GPUs. Returns # newly added."""
    base = config.get("base_url", "https://www.techpowerup.com").rstrip("/")
    dmin = config.get("timing.discover_delay_min", 1.0)
    dmax = config.get("timing.discover_delay_max", 2.0)

    # Warm up / pass any challenge with a real page first.
    from .challenge import wait_for_resolution

    page = session.new_page()
    try:
        page.goto(f"{base}/gpu-specs/", wait_until="domcontentloaded",
                  timeout=config.get("timing.nav_timeout_ms", 60000))
        wait_for_resolution(page, timeout_seconds=config.get("timing.challenge_wait_seconds", 60))
    finally:
        try:
            page.close()
        except Exception:
            pass

    ctx = session.context
    resp = ctx.request.get(f"{base}/gpu-specs/?architecture=&ajax")
    data = _json_or_none(resp)
    archs = parse_architectures(data.get("filters", "")) if data else []
    runtime.log(f"discovery: found {len(archs)} architectures")
    if not archs:
        runtime.log("discovery: no architectures found — aborting")
        return 0

    total_added = 0
    for arch in archs:
        value, count = arch["value"], arch["count"]
        pages = max(1, math.ceil(count / 100)) if count else 1
        seen: set[str] = set()
        for p in range(1, pages + 1):
            # Page 1 has no `p` param (the site rejects `p=1`); paging starts at p=2.
            pstr = f"&p={p}" if p > 1 else ""
            url = f"{base}/gpu-specs/?architecture={value}{pstr}&ajax"
            d = _json_or_none(ctx.request.get(url))
            if d is None:
                runtime.log(f"discovery: bad response {arch['name']} p{p}, skipping rest")
                break
            gpus = parse_gpu_links(d.get("list", ""))
            if not gpus:
                break
            added_here = 0
            for g in gpus:
                if g["id"] in seen:
                    continue
                seen.add(g["id"])
                before = queue.store.has(g["id"])
                queue.add_url(g["url"], source="architecture", name=g["name"])
                if not before and queue.store.has(g["id"]):
                    added_here += 1
            total_added += added_here
            time.sleep(random.uniform(dmin, dmax))
        runtime.log(f"discovery: {arch['name']} -> {len(seen)} GPUs (new +{total_added} so far)")
        time.sleep(random.uniform(dmin, dmax))

    runtime.log(f"discovery complete: {total_added} new GPUs enqueued across {len(archs)} architectures")
    return total_added
