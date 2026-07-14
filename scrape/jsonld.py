"""
Extract events from a page without knowing anything about its markup.

Two passes:

1. schema.org JSON-LD in <script type="application/ld+json">. This is the contract
   the venue publishes for Google's rich results. If it exists, it survives redesigns,
   and it is the only kind of scraping worth doing at scale.

2. Embedded state blobs — __NEXT_DATA__, __NUXT__, window.__APOLLO_STATE__. Most
   gallery sites (Zwirner, Pace, Ropac) are Next.js and ship their whole listing
   payload as JSON in the page. We walk the tree looking for anything that quacks
   like an event: a name/title plus a start date. Less durable than JSON-LD but far
   more durable than CSS selectors.

Nothing here parses HTML structure. That's deliberate.
"""
import json
import re

from bs4 import BeautifulSoup

EVENT_TYPES = {
    "event", "exhibitionevent", "theaterevent", "musicevent", "danceevent",
    "screeningevent", "socialevent", "educationevent", "festival",
    "visualartsevent", "literaryevent", "comedyevent", "performance",
}

DATE_KEYS = ("startDate", "start_date", "startdate", "start", "date",
             "beginDate", "dateStart")
NAME_KEYS = ("name", "title", "headline", "eventTitle")
END_KEYS = ("endDate", "end_date", "enddate", "end", "dateEnd")
URL_KEYS = ("url", "link", "permalink", "slug", "href")

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _types(obj):
    t = obj.get("@type") or obj.get("type") or ""
    if isinstance(t, list):
        return {str(x).lower() for x in t}
    return {str(t).lower()}


def _walk(node, out, depth=0):
    """Yield every dict in a nested structure."""
    if depth > 14:
        return
    if isinstance(node, dict):
        out.append(node)
        for v in node.values():
            _walk(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out, depth + 1)


def _first(obj, keys):
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for kk in ("@value", "value", "name", "url"):
                if isinstance(v.get(kk), str) and v[kk].strip():
                    return v[kk].strip()
    return None


def _looks_like_event(obj):
    if not isinstance(obj, dict):
        return False
    if _types(obj) & EVENT_TYPES:
        return True
    # duck-typing pass for embedded state blobs
    d = _first(obj, DATE_KEYS)
    n = _first(obj, NAME_KEYS)
    return bool(d and n and ISO_DATE.match(d))


def _location(obj):
    loc = obj.get("location")
    if isinstance(loc, dict):
        return loc.get("name") or (loc.get("address") or {}).get("addressLocality")
    if isinstance(loc, str):
        return loc
    return None


def _to_event(obj):
    start = _first(obj, DATE_KEYS)
    name = _first(obj, NAME_KEYS)
    if not start or not name:
        return None
    return {
        "title": name,
        "start": start,
        "end": _first(obj, END_KEYS),
        "url": _first(obj, URL_KEYS),
        "location": _location(obj),
        "status": obj.get("eventStatus"),
    }


def _json_blocks(soup, html):
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            # some sites emit multiple objects or trailing commas
            for chunk in re.findall(r"\{.*?\}(?=\s*[,\]]|\s*$)", raw, re.S):
                try:
                    yield json.loads(chunk)
                except json.JSONDecodeError:
                    pass

    for tag in soup.find_all("script", id=re.compile(r"__NEXT_DATA__|__NUXT_DATA__")):
        try:
            yield json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

    m = re.search(r"window\.__(?:NUXT|APOLLO_STATE|INITIAL_STATE)__\s*=\s*(\{.*?\});?\s*</script>",
                  html, re.S)
    if m:
        try:
            yield json.loads(m.group(1))
        except json.JSONDecodeError:
            pass


def extract(html):
    """Return a list of raw event dicts found anywhere in the page's JSON."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = []
    for block in _json_blocks(soup, html):
        _walk(block, nodes)

    seen, events = set(), []
    for obj in nodes:
        if not _looks_like_event(obj):
            continue
        ev = _to_event(obj)
        if not ev:
            continue
        key = (ev["title"].lower(), ev["start"][:10])
        if key in seen:
            continue
        seen.add(key)
        events.append(ev)
    return events
