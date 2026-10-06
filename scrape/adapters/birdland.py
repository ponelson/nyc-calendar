"""
Birdland.

WordPress event calendar exposed via admin-ajax. Rendering the calendar page captures
the AJAX response — a flat list of shows. Confirmed fields:
  title (the artist — "Vince Giordano and the Nighthawks"), start (YYYY-MM-DD),
  displayTime ("5:30 PM"), url, venue (HTML naming Birdland vs Birdland Theater).

title is already the performer billing, which is exactly what we want.
"""
import re

from .. import render

TAGS = re.compile(r"<[^>]+>")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AP]M)", re.I)


def _time(s):
    m = TIME_RE.search(s or "")
    if not m:
        return ""
    h, mn, ap = int(m.group(1)), m.group(2), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mn}"


def _venue(s):
    txt = TAGS.sub(" ", s or "")
    return "Birdland Theater" if "theater" in txt.lower() else "Birdland"


def run(venue):
    _, payloads = render.render(venue["url"], capture_json=True, scroll=2)
    out, seen = [], set()
    for p in payloads:
        if "admin-ajax" not in p["url"]:
            continue
        body = p["body"]
        rows = body if isinstance(body, list) else (
            body.get("events") or body.get("data") or [])
        for e in rows:
            if not isinstance(e, dict):
                continue
            title = TAGS.sub("", e.get("title") or "").strip()
            day = e.get("start")
            if not title or not day:
                continue
            key = (title, day)
            if key in seen:
                continue
            seen.add(key)
            t = _time(e.get("displayTime"))
            out.append({
                "title": title,
                "start": f"{day}T{t}" if t else day,
                "end": None,
                "url": e.get("url") or venue["url"],
                "location": _venue(e.get("venue")),
            })
    return out
