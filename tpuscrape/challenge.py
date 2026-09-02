"""Detection of the target site's `/.firewall` challenge interstitial.

When the site serves the anti-bot challenge, the HTML is a `noindex` shell with
the SEO <title>/og:meta but *none* of the spec content (no <h1>, no spec <h2>).
Signatures we look for: the `/.firewall` endpoint reference, the multi-stage
pipeline JS (`runPipeline`), the drag-captcha UI, and the missing <h1>.
"""
from __future__ import annotations

CHALLENGE_MARKERS = (
    "/.firewall",
    "runPipeline",
    "drag-captcha",
    "One more step",
    "noindex,nofollow,noarchive",
)


def detect(page) -> str | None:
    """Return a human-readable reason if the page is a challenge, else None."""
    try:
        url = page.url or ""
    except Exception:
        url = ""
    if "/.firewall" in url:
        return "url contains /.firewall"

    try:
        html = page.content()
    except Exception:
        return None

    low = html.lower()
    for marker in CHALLENGE_MARKERS:
        if marker.lower() in low:
            # A noindex meta alone is a weak signal; only treat it as a
            # challenge if the real spec heading is absent.
            if marker == "noindex,nofollow,noarchive":
                if "<h1" not in low and "graphics processor" not in low:
                    return "challenge shell (noindex, no spec content)"
            else:
                return f"challenge marker: {marker}"
    return None


def wait_for_resolution(page, timeout_seconds: float = 60, poll: float = 2.0):
    """Poll until the challenge resolves (real content appears).

    Returns (resolved: bool, reason: str|None).  In a genuine browser the
    fingerprinting + proof-of-work usually resolves on its own in a few seconds;
    the drag-captcha (manual fallback) needs a human.
    """
    import time

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        reason = detect(page)
        if reason is None:
            return True, None
        time.sleep(poll)
    return False, detect(page)
