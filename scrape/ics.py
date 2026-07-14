"""iCalendar feeds. When a venue offers one, it beats every other strategy."""
import re
from datetime import datetime

LINE = re.compile(r"^([A-Z\-]+)(;[^:]*)?:(.*)$")


def _unfold(text):
    out = []
    for line in text.splitlines():
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _dt(value):
    value = value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            continue
    return None


def extract(text):
    events, cur = [], None
    for line in _unfold(text):
        if line.startswith("BEGIN:VEVENT"):
            cur = {}
            continue
        if line.startswith("END:VEVENT"):
            if cur and cur.get("title") and cur.get("start"):
                events.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        m = LINE.match(line)
        if not m:
            continue
        key, _params, val = m.groups()
        val = val.replace("\\,", ",").replace("\\n", " ").strip()
        if key == "SUMMARY":
            cur["title"] = val
        elif key == "DTSTART":
            cur["start"] = _dt(val)
        elif key == "DTEND":
            cur["end"] = _dt(val)
        elif key == "URL":
            cur["url"] = val
        elif key == "LOCATION":
            cur["location"] = val
    return [e for e in events if e.get("start")]


ICS_HINTS = ("/events.ics", "/calendar.ics", "?ical=1", "/events/?ical=1",
             "/feed/?post_type=tribe_events", "/events/feed/")


def candidate_urls(base):
    """The Events Calendar (WordPress) and most CMSes expose predictable ICS paths.
    probe.py tries these before falling back to HTML."""
    base = base.rstrip("/")
    root = "/".join(base.split("/")[:3])
    return [base + "?ical=1", root + "/events/?ical=1", root + "/events.ics",
            root + "/calendar.ics"]
