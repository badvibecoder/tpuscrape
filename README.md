# tpuscrape

A scraper for GPU specifications from the TechPowerUp GPU database
(`/gpu-specs/`). It walks the site's Relative Performance chart *and* the full
Architecture index to enumerate every GPU, then saves each one as a structured
`spec.yaml` in its own folder.

**Why a real browser?** The site serves an aggressive anti-bot challenge
(fingerprinting + proof-of-work + a drag-captcha fallback). `tpuscrape` launches
your real Chrome and drives it over the DevTools protocol, so it passes like a
normal browser. If a challenge ever needs a human, it pauses and lets you solve
it in the visible Chrome window.

## Features

- Traverses the Relative Performance chart and (optionally) the complete
  Architecture index (`--discover`).
- Saves structured specs (clocks, memory, render config, theoretical/matrix
  performance, board design, features, notes, boards, performance chart).
- Deduplicates by GPU id and resumes from a SQLite state file.
- Randomizes which GPU is scraped next, with a configurable backoff.
- Local status dashboard with pause/resume and an "add URLs" box.
- Opt-in editorial/visual content (see **Flags**).

## Requirements

- Python 3.10+
- Google Chrome (or any Chromium) — the path is set in `config.yaml`
  (`browser.chrome_binary`).
- A display, because the browser runs headed so you can solve challenges.

## Getting started

```bash
git clone <your-repo-url>
cd <repo>

# create a virtualenv and install
python -m venv .venv
.venv/bin/pip install -r requirements.txt
# or, for a `tpuscrape` console command:
# .venv/bin/pip install -e .
```

Edit `config.yaml` if your Chrome binary is elsewhere. The default seed is the
RTX 5090 page; the Relative Performance chart on that page seeds the frontier.

## Usage

```bash
# Scrape 50 GPUs (random pick, polite 2–6s backoff), with the dashboard at :8080
.venv/bin/python tpuscrape/main.py --max 50

# Scrape everything in the performance chart (~175 GPUs), then exit
.venv/bin/python tpuscrape/main.py --stop-when-empty

# Discover EVERY GPU (all 105 architectures, ~3,300+ GPUs) and enqueue, then scrape all
.venv/bin/python tpuscrape/main.py --discover --stop-when-empty

# Only enumerate + enqueue every GPU by architecture (no scraping)
.venv/bin/python tpuscrape/main.py --discover-only

# Wide backoff for a long, low-profile run (30–60s between pages)
.venv/bin/python tpuscrape/main.py --delay-min 30 --delay-max 60 --discover --stop-when-empty
```

## Flags

| Flag | Effect |
|---|---|
| `--max N` | scrape at most N GPUs (this run), then exit |
| `--stop-when-empty` | exit when the queue is empty |
| `--discover` | enumerate all architectures and enqueue every GPU before scraping |
| `--discover-only` | enumerate/enqueue, then exit without scraping |
| `--delay-min N` / `--delay-max N` | random backoff range between GPU page fetches (default 2–6s) |
| `--include-description` | include the editorial/prose description text (default off) |
| `--include-images` | download card/chip images into an `images/` folder (default off) |
| `--keep-html` | keep a copy of the raw page HTML (default off) |
| `--no-status` | don't start the web dashboard |

The `--include-*` / `--keep-html` flags are **opt-in**: by default `spec.yaml`
contains only the structured factual specs and no images or raw HTML. You can
also set their defaults in `config.yaml` under `scrape:`.

## Add GPUs not in the performance chart

Most workstation/datacenter/older cards aren't in the Relative Performance
chart. Two ways to add them:

- Append one URL per line to `scripts/seed_urls.txt`, or
- Paste URLs into the status dashboard's "Add URLs" box.

Use the exact `/gpu-specs/<slug>.c####` URL. `--discover` already covers the
whole database, so the feed is mainly for targeted additions.

## Output

```
data/
├── index.json               # aggregate list: id, name, url, key specs
└── <gpu-slug>/
    └── spec.yaml            # name, id, url, top specs, all spec sections,
                             # notes, boards, relative-performance chart
                             # (+ description/images/page.html only if enabled)
state/scraper.db             # resume state (gitignored)
```

## Notes

- Stop and restart anytime — completed GPUs are never re-scraped.
- Keep the site's `robots.txt`/terms in mind and use a polite backoff.
- The status dashboard is at `http://127.0.0.1:8080` while running.
