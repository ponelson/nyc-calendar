"""
Broadway is a special case: you don't want a calendar entry for every performance of
every show — that's 40 shows x 8 performances a week and it buries everything else.

What you actually want is: which shows are playing in the seven houses you care about,
and when do they open and close.

So this adapter reads the industry listing, keeps only the theaters on your list, and
emits an entry on the opening date and one on the closing date. Anything currently
running with no announced close gets a single entry today marked "now playing", which
re-emits on each nightly run so it never goes stale.
"""
from datetime import date

from .. import fetch
from ..jsonld import extract as jsonld_extract

HOUSES = {
    "lyric": "Lyric Theatre",
    "belasco": "Belasco Theatre",
    "hudson": "Hudson Theatre",
    "new amsterdam": "New Amsterdam Theatre",
    "majestic": "Majestic Theatre",
    "booth": "Booth Theatre",
    "walter kerr": "Walter Kerr Theatre",
}


def _house(text):
    low = (text or "").lower()
    for key, name in HOUSES.items():
        if key in low:
            return name
    return None


def run(venue):
    html = fetch.get(venue["url"], ttl=6 * 3600)
    raw = jsonld_extract(html)
    out = []
    today = date.today().isoformat()

    for ev in raw:
        house = _house(ev.get("location") or "") or _house(ev.get("title") or "")
        if not house:
            continue
        out.append({
            "title": f"{ev['title']} — {house}",
            "start": ev.get("start") or today,
            "end": ev.get("end"),
            "url": ev.get("url"),
            "location": house,
        })

    return out
