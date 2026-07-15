"""
New York City Ballet.

The calendar page fetches one JSON document at /season-and-tickets/events/<seasonId>
— the whole season in a flat list. Confirmed field names (from the live feed):

    title        performance title
    perf_date    ISO datetime with -04:00 offset
    perf_type    "Repertory", "Full-Length", etc. — also education programs, dropped
    event_link   canonical URL

The season id in the path rolls over, so we read it out of the calendar page rather
than hard-coding, falling back to the last known id if discovery fails.
"""
import json
import re

from .. import fetch

FEED = "https://www.nycballet.com/season-and-tickets/events/{sid}"
LAST_KNOWN = 16
ID_IN_PAGE = re.compile(r"/season-and-tickets/events/(\d+)")

DROP = ("workshop", "class", "essentials", "talk", "conversation", "seminar",
        "lecture", "pre-performance", "insight", "student", "open house",
        "educate", "public-program", "public program")


def _season(page_html):
    ids = [int(x) for x in ID_IN_PAGE.findall(page_html or "")]
    return max(ids) if ids else LAST_KNOWN


def run(venue):
    try:
        page = fetch.get(venue["url"], ttl=12 * 3600)
    except Exception:  # noqa: BLE001
        page = ""
    sid = _season(page)

    data = json.loads(fetch.get(FEED.format(sid=sid), ttl=6 * 3600))
    items = data if isinstance(data, list) else data.get("events", [])

    out = []
    for e in items:
        title = (e.get("title") or "").strip()
        date = e.get("perf_date")
        if not title or not date:
            continue
        haystack = f"{title} {e.get('perf_type','')} {e.get('event_link','')}".lower()
        if any(w in haystack for w in DROP):
            continue
        out.append({
            "title": title,
            "start": date,
            "end": None,
            "url": e.get("event_link") or venue["url"],
            "location": "David H. Koch Theater",
        })
    return out
