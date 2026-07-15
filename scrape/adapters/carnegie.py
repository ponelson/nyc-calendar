"""
Carnegie Hall.

The calendar is an Algolia-backed list that loads 10 events per scroll (nbHits ~664).
We render with scroll enabled, collect every Algolia response fired along the way, and
dedupe. No API key needed — we read exactly what the page reads.

Confirmed hit fields:
    title       event title
    date        human string, "Wednesday, Jul 15, 2026"  <- we parse this
    startdate   millisecond epoch (unused; it's a float, not ISO)
    time        "6 PM"
    url         relative path
    facility    hall / venue name
"""
from datetime import datetime

from .. import render

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
     "Nov", "Dec"], 1)}


def _date(s):
    # "Wednesday, Jul 15, 2026" -> 2026-07-15
    try:
        parts = s.replace(",", "").split()
        mon = MONTHS[parts[1][:3]]
        return datetime(int(parts[3]), mon, int(parts[2])).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _time(s):
    # "6 PM" / "6:30 PM" -> 18:00 / 18:30
    try:
        return datetime.strptime(s.strip().upper().replace(" ", ""),
                                 "%I%p").strftime("%H:%M")
    except ValueError:
        try:
            return datetime.strptime(s.strip().upper().replace(" ", ""),
                                     "%I:%M%p").strftime("%H:%M")
        except ValueError:
            return ""


def run(venue):
    _, payloads = render.render(venue["url"], capture_json=True, scroll=12)

    seen, out = set(), []
    for p in payloads:
        if "algolia.net" not in p["url"]:
            continue
        body = p["body"]
        results = body.get("results", [body]) if isinstance(body, dict) else []
        for res in results:
            for h in res.get("hits", []):
                title = h.get("title")
                day = _date(h.get("date", ""))
                if not title or not day:
                    continue
                url = h.get("url", "")
                if url.startswith("/"):
                    url = "https://www.carnegiehall.org" + url
                key = (title, day)
                if key in seen:
                    continue
                seen.add(key)
                t = _time(h.get("time", ""))
                out.append({
                    "title": title.strip(),
                    "start": f"{day}T{t}" if t else day,
                    "end": None,
                    "url": url or venue["url"],
                    "location": h.get("facility") or "Carnegie Hall",
                })
    return out
