"""
Carnegie Hall.

The calendar is Algolia-backed (index prod_Events, ~660 upcoming hits) but the page
asks for ten at a time and headless scrolling doesn't trigger the next batch. v1 got
stuck at those ten — five days of listings.

v2 renders the page once to capture Carnegie's own Algolia request, then replays it
from inside the page at full size (see scrape/algolia.py). The original ten hits stay
as a fallback if the replay is refused.

Confirmed hit fields:
    title       event title
    date        human string, "Wednesday, Jul 15, 2026"  <- parsed
    time        "6 PM"
    url         relative path
    facility    hall — Stern Auditorium / Zankel Hall / Weill Recital Hall
"""
from datetime import datetime

from .. import algolia, render

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
     "Nov", "Dec"], 1)}

# Halls get short names in the venue line; anything else passes through.
HALLS = {"stern": "Stern Auditorium", "zankel": "Zankel Hall", "weill": "Weill Recital Hall",
         "resnick": "Resnick Education Wing"}

SKIP_PREFIX = ("cancelled", "canceled", "postponed")


def _date(s):
    # "Wednesday, Jul 15, 2026" -> 2026-07-15
    try:
        parts = (s or "").replace(",", "").split()
        mon = MONTHS[parts[1][:3]]
        return datetime(int(parts[3]), mon, int(parts[2])).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _time(s):
    s = (s or "").strip().upper().replace(" ", "").replace(".", "")
    for fmt in ("%I%p", "%I:%M%p"):
        try:
            return datetime.strptime(s, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return ""


def _hall(fac):
    f = (fac or "").strip()
    low = f.lower()
    for k, name in HALLS.items():
        if k in low:
            return name
    return f


NOTE = {}


def run(venue):
    html, payloads, extra = render.render(
        venue["url"], capture_json=True, scroll=2, after=algolia.replay)

    bodies = [p["body"] for p in payloads if "algolia" in p["url"]]
    extra = extra if isinstance(extra, dict) else {}
    replayed = extra.get("bodies") or []
    bodies += replayed

    seen, out = set(), []
    for h in algolia.hits(bodies):
        title = (h.get("title") or "").strip()
        day = _date(h.get("date", ""))
        if not title or not day:
            continue
        if title.lower().startswith(SKIP_PREFIX):
            continue
        key = (title.lower(), day)
        if key in seen:
            continue
        seen.add(key)
        url = h.get("url", "") or ""
        if url.startswith("/"):
            url = "https://www.carnegiehall.org" + url
        t = _time(h.get("time", ""))
        out.append({
            "title": title,
            "start": f"{day}T{t}" if t else day,
            "end": None,
            "url": url or venue["url"],
            "room": _hall(h.get("facility")),
        })

    days = sorted(e["start"][:10] for e in out)
    NOTE[venue["id"]] = (f"{len(out)} kept {days[0] if days else ''}..{days[-1] if days else ''}; "
                         + " | ".join(extra.get("notes") or [str(extra.get("error", ""))])
                         + "; " + render.describe(payloads, 2))[:700]
    if not out:
        raise RuntimeError(f"no hits; {NOTE.get(venue['id'],'')}")
    return out
