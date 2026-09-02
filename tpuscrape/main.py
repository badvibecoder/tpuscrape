#!/usr/bin/env python3
"""Entrypoint for tpuscrape."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tpuscrape.config import load_config  # noqa: E402
from tpuscrape.orchestrator import Scraper  # noqa: E402
from tpuscrape.frontier import Queue  # noqa: E402
from tpuscrape.runtime import RuntimeState  # noqa: E402
from tpuscrape.status import create_app, start_server  # noqa: E402
from tpuscrape.store import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="tpuscrape — GPU specs scraper")
    ap.add_argument("--max", type=int, default=None, help="scrape at most N GPUs, then exit")
    ap.add_argument(
        "--stop-when-empty",
        action="store_true",
        help="exit when the queue is empty (scrape the whole list and stop)",
    )
    ap.add_argument(
        "--discover",
        action="store_true",
        help="enumerate all architectures and enqueue every GPU before scraping",
    )
    ap.add_argument(
        "--discover-only",
        action="store_true",
        help="enumerate architectures/enqueue GPUs, then exit without scraping",
    )
    ap.add_argument(
        "--delay-min",
        type=float,
        default=None,
        help="min random backoff between GPU fetches in seconds (default: config, 2.0)",
    )
    ap.add_argument(
        "--delay-max",
        type=float,
        default=None,
        help="max random backoff between GPU fetches in seconds (default: config, 6.0)",
    )
    ap.add_argument(
        "--include-description",
        action="store_true",
        default=None,
        help="include the editorial/prose description text in spec.yaml (default: off)",
    )
    ap.add_argument(
        "--include-images",
        action="store_true",
        default=None,
        help="download card/chip images into an images/ folder (default: off)",
    )
    ap.add_argument(
        "--keep-html",
        action="store_true",
        default=None,
        help="keep a copy of the raw page HTML (default: off)",
    )
    ap.add_argument("--no-status", action="store_true", help="do not start the web dashboard")
    args = ap.parse_args()

    cfg = load_config()
    store = Store(cfg)
    queue = Queue(cfg, store)
    runtime = RuntimeState()

    if not args.no_status:
        app = create_app(store, runtime, queue)
        host = cfg.get("status.host", "127.0.0.1")
        port = cfg.get("status.port", 8080)
        start_server(app, host, port)
        print(f"✅ Status page: http://{host}:{port}", flush=True)

    scraper = Scraper(cfg, store, queue, runtime)
    try:
        scraper.run(
            max_gpus=args.max,
            stop_when_empty=args.stop_when_empty,
            discover=args.discover or args.discover_only,
            discover_only=args.discover_only,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            include_description=args.include_description,
            include_images=args.include_images,
            keep_html=args.keep_html,
        )
    except KeyboardInterrupt:
        print("\nInterrupted — shutting down.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
