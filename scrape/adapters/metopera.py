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


NOTE = {}


def _via_browser():
    """The Met's CDN refuses plain clients from cloud IPs (every CI run since Oct 7
    returned nothing). Load the calendar in Chromium, then ask the same API from inside
    the page; if fetch() is refused, navigate the tab to the API URL itself."""
    from .. import render

    def after(page, payloads):
        got, notes = [], [f"calendar page: {page.title()[:60]!r}, {len(page.content())} chars"]
        for start, end in _windows():
            api = API.format(start=start.isoformat(), end=end.isoformat())
            status, data = render.page_fetch(page, api)
            if data is None:
                try:
                    resp = page.goto(api, timeout=20_000)
                    status = resp.status if resp else 0
                    data = json.loads(page.inner_text("body")) if status == 200 else None
                except Exception as e:  # noqa: BLE001
                    status = type(e).__name__
            notes.append(f"{start.isoformat()}:{status}")
            if data is not None:
                got.append(data)
        return {"bodies": got, "notes": notes}

    _, payloads, extra = render.render(CAL.format(start=date.today().isoformat()),
                                       capture_json=True, after=after)
    extra = extra if isinstance(extra, dict) else {}
    bodies = [p["body"] for p in payloads if "ace-api" in p["url"]] + (extra.get("bodies") or [])
    return bodies, payloads, extra.get("notes") or [str(extra.get("error", ""))]


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
    payloads, notes = [], [f"direct API: {sum(1 for b in bodies if _events(b))}/6 windows"]
    if not any(_events(b) for b in bodies):
        bodies, payloads, more = _via_browser()
        notes += more

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
    from .. import render
    NOTE[venue["id"]] = ("; ".join(notes) + "; " + render.describe(payloads, 2))[:700]
    if not out:
        raise RuntimeError("no events from API or browser; " + NOTE[venue["id"]])
    return out
