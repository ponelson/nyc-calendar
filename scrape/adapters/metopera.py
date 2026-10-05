"""
Metropolitan Opera.

The calendar page calls a clean dated JSON API:
  https://www.metopera.org/ace-api/events/?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD

Confirmed fields: name, eventDate (ISO), eventTimeString, location, composer,
artistCredits, categories (['Tours'] etc.), synopsis, viewDetailCtaUrl.

We pull a rolling window and keep staged operas, dropping tours, talks, and
backstage programs via the categories field.
"""
import json
import urllib.request
from datetime import date, timedelta

API = "https://www.metopera.org/ace-api/events/?startDate={start}&endDate={end}"
DROP_CATS = {"tours", "talks", "backstage", "education", "student"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-calendar/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _events(obj, depth=0):
    if depth > 8:
        return None
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "eventDate" in obj[0]:
            return obj
        for x in obj:
            r = _events(x, depth + 1)
            if r:
                return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = _events(v, depth + 1)
            if r:
                return r
    return None


def run(venue):
    today = date.today()
    out, seen = [], set()
    # pull ~6 one-month windows forward
    for i in range(6):
        start = today + timedelta(days=30 * i)
        end = start + timedelta(days=31)
        try:
            data = _get(API.format(start=start.isoformat(), end=end.isoformat()))
        except Exception:  # noqa: BLE001
            continue
        for e in (_events(data) or []):
            name = (e.get("name") or "").strip()
            when = e.get("eventDate")
            if not name or not when:
                continue
            cats = [str(c).lower() for c in (e.get("categories") or [])]
            if any(c in DROP_CATS for c in cats):
                continue
            key = (name, when[:10])
            if key in seen:
                continue
            seen.add(key)
            # fold the composer/cast into the title where present
            title = name
            comp = (e.get("composer") or "").strip()
            if comp and comp.lower() not in name.lower():
                title = f"{comp}: {name}"
            out.append({
                "title": title,
                "start": when,
                "end": None,
                "url": "https://www.metopera.org" + (e.get("viewDetailCtaUrl") or e.get("buyTicketCtaUrl") or ""),
                "location": e.get("location") or "Metropolitan Opera",
            })
    return out
