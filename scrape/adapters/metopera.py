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


HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.metopera.org/Calendar/",
}
CAL = "https://www.metopera.org/Calendar/?date={start}&layout=C&categories=On%20Stage"


def _get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _windows():
    today = date.today()
    for i in range(6):
        start = today + timedelta(days=30 * i)
        yield start, start + timedelta(days=31)


def _via_browser():
    """The Met's CDN refuses plain clients from cloud IPs (every CI run since Oct 7
    returned nothing). Load the calendar in Chromium and ask the same API from inside
    the page, where the Met's own cookies apply."""
    from .. import render

    def after(page, payloads):
        got = []
        for start, end in _windows():
            _, data = render.page_fetch(page, API.format(start=start.isoformat(),
                                                          end=end.isoformat()))
            if data:
                got.append(data)
        return got

    _, payloads, extra = render.render(CAL.format(start=date.today().isoformat()),
                                       capture_json=True, after=after)
    bodies = [p["body"] for p in payloads if "ace-api" in p["url"]]
    if isinstance(extra, list):
        bodies += extra
    return bodies, payloads


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


def _rows(bodies):
    for data in bodies:
        for e in (_events(data) or []):
            yield e


def run(venue):
    bodies = []
    for start, end in _windows():
        try:
            bodies.append(_get(API.format(start=start.isoformat(), end=end.isoformat())))
        except Exception:  # noqa: BLE001
            continue
    payloads = []
    if not any(_events(b) for b in bodies):
        bodies, payloads = _via_browser()

    out, seen = [], set()
    for e in _rows(bodies):
        name = (e.get("name") or "").strip()
        when = e.get("eventDate")
        if not name or not when:
            continue
        cats = [str(c).lower() for c in (e.get("categories") or [])]
        if any(c in DROP_CATS for c in cats):
            continue
        key = (name, when[:16])
        if key in seen:
            continue
        seen.add(key)
        title = name
        comp = (e.get("composer") or "").strip()
        if comp and comp.lower() not in name.lower():
            title = f"{comp}: {name}"
        out.append({
            "title": title,
            "start": when,
            "end": None,
            "url": "https://www.metopera.org" + (e.get("viewDetailCtaUrl") or e.get("buyTicketCtaUrl") or ""),
        })
    if not out:
        from .. import render
        raise RuntimeError("no events from API or browser; " + render.describe(payloads))
    return out
