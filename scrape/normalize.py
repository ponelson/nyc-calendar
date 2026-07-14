"""
Turn whatever the venue gave us into the one schema the calendar reads:

    {id, date: "YYYY-MM-DD", time: "HH:MM"|"", title, venue, cat, url, source}

The interesting decision here is how to handle runs.

A concert is a point in time. An exhibition is a season — the Vermeer show is "on"
for four months, and writing it into 120 calendar cells would drown everything else.
So:

  * runs of 14 days or fewer  -> one entry per day (a Joyce run, a Broadway week)
  * longer runs               -> two entries: "Opens" and "Final day"

That way a gallery show announces itself twice, when either fact is actionable, and
the grid stays readable.
"""
import hashlib
import re
from datetime import date, datetime, timedelta

MAX_DAYS_EXPANDED = 14
HORIZON_DAYS = 400

_TZ = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def parse_dt(value):
    if not value:
        return None, None
    v = _TZ.sub("", str(value).strip()).replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(v, fmt)
        except ValueError:
            continue
        has_time = "%H" in fmt
        return dt.date(), (dt.strftime("%H:%M") if has_time else "")
    # last resort: a leading ISO date
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return date(*map(int, m.groups())), ""
    return None, None


def _eid(venue_id, day, title):
    h = hashlib.sha1(f"{venue_id}|{day}|{title}".encode()).hexdigest()[:10]
    return f"s{h}"


def _clean(title):
    title = re.sub(r"\s+", " ", title or "").strip()
    title = re.sub(r"^(Buy tickets?|Tickets?):?\s*", "", title, flags=re.I)
    return title[:120]


def normalize(raw_events, venue):
    """raw_events: list of {title,start,end,url,location}. Returns app-schema events."""
    today = date.today()
    horizon = today + timedelta(days=HORIZON_DAYS)
    floor = today - timedelta(days=1)
    exclude = [w.lower() for w in venue.get("exclude", [])]
    out = {}

    for raw in raw_events:
        title = _clean(raw.get("title"))
        if not title:
            continue
        if any(w in title.lower() for w in exclude):
            continue
        if str(raw.get("status", "")).lower().endswith("cancelled"):
            continue

        start, time_ = parse_dt(raw.get("start"))
        if not start:
            continue
        end, _ = parse_dt(raw.get("end"))
        end = end or start
        if end < start:
            end = start

        url = raw.get("url") or venue["url"]
        if url.startswith("/"):
            root = "/".join(venue["url"].split("/")[:3])
            url = root + url

        span = (end - start).days + 1

        if span <= MAX_DAYS_EXPANDED:
            days = [(start + timedelta(days=i), title, time_)
                    for i in range(span)]
        else:
            days = [(start, f"{title} — opens", ""),
                    (end, f"{title} — final day", "")]

        for day, label, t in days:
            if day < floor or day > horizon:
                continue
            ev = {
                "id": _eid(venue["id"], day.isoformat(), label),
                "date": day.isoformat(),
                "time": t or "",
                "title": label,
                "venue": venue["name"],
                "cat": venue["cat"],
                "url": url,
                "src": venue["id"],
            }
            out[ev["id"]] = ev

    return list(out.values())
