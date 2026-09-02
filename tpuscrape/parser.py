"""Parse a GPU specs page (final rendered HTML) into a dict."""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag


def _clean(text: str | None) -> str:
    if text is None:
        return ""
    return " ".join(text.replace("\xa0", " ").split())


def _multiline(el: Tag) -> str:
    """Get text with <br> converted to newlines (line breaks preserved)."""
    for br in el.find_all("br"):
        br.replace_with("\n")
    text = el.get_text().replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _extract_links(dd: Tag | None) -> list[dict]:
    if dd is None:
        return []
    out = []
    for a in dd.find_all("a", href=True):
        out.append({"text": _clean(a.get_text()), "href": a.get("href")})
    return out


def _parse_relative_performance(section: Tag) -> list[dict]:
    entries = []
    for e in section.select(".gpudb-relative-performance-entry"):
        title_el = e.select_one(".gpudb-relative-performance-entry__title")
        link = e.select_one("a.gpudb-relative-performance-entry__link")
        num_el = e.select_one(".gpudb-relative-performance-entry__number")
        classes = e.get("class") or []
        try:
            pct = float(e.get("data-length") or 0)
        except (TypeError, ValueError):
            pct = None
        entries.append(
            {
                "name": _clean(title_el.get_text()) if title_el else "",
                "href": link.get("href") if link else None,
                "title": link.get("title") if link else None,
                "percent": pct,
                "display": _clean(num_el.get_text()) if num_el else "",
                "is_primary": "gpudb-relative-performance-entry--primary" in classes,
            }
        )
    return entries


def _parse_notes(section: Tag) -> dict:
    h2 = section.select_one("h2")
    title = _clean(h2.get_text()) if h2 else "Notes"
    td = section.select_one("td.p") or section.select_one("td")
    text = _multiline(td) if td else ""
    return {"title": title, "text": text}


def _parse_boards(section: Tag) -> dict:
    h2 = section.select_one("h2")
    title = _clean(h2.get_text()) if h2 else "Retail boards"
    m = re.search(r"\((\d+)\)", title)
    count = int(m.group(1)) if m else None
    boards = []
    table = section.select_one("table")
    if table is not None:
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue
            boards.append(
                {
                    "name": _clean(tds[0].get_text()) if len(tds) > 0 else "",
                    "gpu_clock": _clean(tds[1].get_text()) if len(tds) > 1 else "",
                    "boost_clock": _clean(tds[2].get_text()) if len(tds) > 2 else "",
                    "memory_clock": _clean(tds[3].get_text()) if len(tds) > 3 else "",
                    "other_changes": _clean(tds[4].get_text()) if len(tds) > 4 else "",
                }
            )
    return {"title": title, "count": count, "boards": boards}


def _parse_images(soup: BeautifulSoup) -> list[dict]:
    images: list[dict] = []
    for a in soup.select("a.gpudb-large-image__item"):
        img = a.select_one("img")
        images.append(
            {
                "label": _clean(img.get("alt")) if img and img.get("alt") else "Front",
                "large_url": a.get("href", ""),
                "thumb_url": img.get("src", "") if img else "",
            }
        )
    for item in soup.select(".gpudb-filmstrip__item"):
        a = item.select_one("a")
        if a is None:
            continue
        img = a.select_one("img")
        title_el = item.select_one(".gpudb-filmstrip__title")
        label = _clean(title_el.get_text()) if title_el else (_clean(img.get("alt")) if img else "")
        images.append(
            {
                "label": label,
                "large_url": a.get("href", ""),
                "thumb_url": img.get("src", "") if img else "",
            }
        )
    return images


def parse_html(html: str, url: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.select_one("h1.gpudb-name")
    name = _clean(h1.get_text()) if h1 else ""

    slug, gpu_id = "", ""
    m = re.search(r"gpu-specs/([a-z0-9-]+)\.c(\d+)", url)
    if m:
        slug, gpu_id = m.group(1), m.group(2)

    # Top summary strip under the name
    top_specs: list[dict] = []
    for entry in soup.select("dl.gpudb-specs-large .gpudb-specs-large__entry"):
        dt = entry.select_one(".gpudb-specs-large__title")
        dd = entry.select_one(".gpudb-specs-large__value")
        top_specs.append(
            {"label": _clean(dt.get_text()) if dt else "", "value": _clean(dd.get_text()) if dd else ""}
        )

    # Prose description
    desc = soup.select_one("div.desc")
    description = _multiline(desc) if desc else ""

    # Recommended gaming resolutions
    resolutions = [
        _clean(li.get_text())
        for li in soup.select(".gpudb-recommended-resolutions__entry")
    ]

    images = _parse_images(soup)

    sections: dict[str, list[dict]] = {}
    relative_performance: list[dict] = []
    notes: dict = {}
    boards: dict = {}

    for sec in soup.select("section.details"):
        classes = set(sec.get("class") or [])
        h2 = sec.select_one("h2")
        title = _clean(h2.get_text()) if h2 else ""
        if not title:
            continue

        if "gpudb-relative-performance" in classes:
            relative_performance = _parse_relative_performance(sec)
            continue
        if "notes" in classes:
            notes = _parse_notes(sec)
            continue
        if "customboards" in classes:
            boards = _parse_boards(sec)
            continue

        pairs: list[dict] = []
        for dl in sec.select("dl"):
            dt = dl.select_one("dt")
            dd = dl.select_one("dd")
            if dt is None:
                continue
            pairs.append(
                {
                    "label": _clean(dt.get_text()),
                    "value": _clean(dd.get_text()) if dd else "",
                    "links": _extract_links(dd),
                }
            )
        sections[title] = pairs

    return {
        "name": name,
        "id": gpu_id,
        "slug": slug,
        "url": url,
        "description": description,
        "top_specs": top_specs,
        "recommended_resolutions": resolutions,
        "images": images,
        "sections": sections,
        "relative_performance": relative_performance,
        "notes": notes,
        "boards": boards,
    }
