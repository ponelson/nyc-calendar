"""
NYC permitted events: parades, street festivals, block parties, plaza events.

Source: NYC Open Data "NYC Permitted Event Information" (dataset tvpp-9vvx), from the
Mayor's Office of Citywide Event Coordination and Management. A real JSON API with
SoQL filtering — no scraping, no rendering. It holds roughly the next month and rolls
forward daily.

Fields: event_name, event_type, event_borough, start_date_time, end_date_time,
event_location, street_closure_type.

The raw feed is ~1,200 Manhattan permits a month, and three quarters are park
"Special Event" bookings: lawn closures, soccer clinics, maintenance. KEEP_TYPES holds
only what a person would go to. One parade files a permit row per street segment, so
rows are collapsed to one per event per day.
"""
import json
import urllib.parse
import urllib.request

DATASET = "tvpp-9vvx"
BASE = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
BOROUGH = "Manhattan"
KEEP_TYPES = {
    "parade", "street festival", "single block festival", "block party", "street event",
    "athletic race / tour", "open culture", "religious event", "plaza partner event",
    "open street partner event",
}

LABELS = {
    "Parade": "Parade", "Street Festival": "Street Festival", "Block Party": "Block Party",
    "Farmers Market": "Market", "Production Event": "Film/TV", "Special Event": "Special Event",
    "Rally": "Rally", "Plaza Event": "Plaza",
}


def _get(params):
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-calendar/2.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def run(venue):
    rows, offset = [], 0
    while offset <= 6000:
        batch = _get({
            "$where": f"event_borough='{BOROUGH}'",
            "$order": "start_date_time",
            "$limit": 1000,
            "$offset": offset,
        })
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000

    out, seen = [], set()
    for r in rows:
        name = (r.get("event_name") or "").strip()
        start = r.get("start_date_time")
        etype = (r.get("event_type") or "").strip()
        if not name or not start:
            continue
        if etype.lower() not in KEEP_TYPES and "parade" not in name.lower():
            continue
        label = LABELS.get(etype, etype)
        title = name if (not label or label.lower() in name.lower()) else f"{name} ({label})"
        loc = (r.get("event_location") or "").strip()
        closure = (r.get("street_closure_type") or "").strip()
        if loc:
            title = f"{title} · {loc[:60]}"
        if closure and closure.lower() not in ("none", "n/a"):
            title = f"{title} — {closure} closure"
        key = (name.lower(), str(start)[:10])
        if key in seen:
            continue
        seen.add(key)
        if str(start)[11:16] == "00:00":
            start = str(start)[:10]
        out.append({
            "title": title,
            "start": start,
            "end": None,   # the permit window includes setup and breakdown; show the day it starts
            "url": "https://www.nyc.gov/site/cecm/index.page",
        })
    return out
