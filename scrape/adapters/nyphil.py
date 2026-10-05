"""
New York Philharmonic.

Calendar page pulls a CloudFront events feed. Confirmed fields:
  Title (may contain <em>), StartDate (ISO), Venue, EventLink, Summary,
  ShowInCalendar, Prefix, Suffix, StrippedTitle.

The feed URL embeds a season id (/Prod/events/<season>/<month>/none/live). We read
the calendar page to find the current feed URL, then page forward a few months.
"""
import json
import re
import urllib.request

from .. import fetch

FEED_RE = re.compile(r"https://[a-z0-9]+\.cloudfront\.net/Prod/events/\d+/\d+/none/live")
TAGS = re.compile(r"<[^>]+>")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-calendar/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _events(obj, depth=0):
    if depth > 8:
        return None
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "StartDate" in obj[0]:
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
    # Need the live feed URL. Render isn't available here; the probe captured it, but
    # to stay API-only we reconstruct by walking season/month from the one we saw.
    # Simpler: fetch the calendar HTML and pull the feed base out of it.
    try:
        html = fetch.get(venue["url"], ttl=12 * 3600)
    except Exception:  # noqa: BLE001
        html = ""
    m = FEED_RE.search(html or "")
    bases = []
    if m:
        bases.append(m.group(0))
    # fallback to the known-good host/path, iterating months
    if not bases:
        bases = ["https://d1c3g0ihb82aph.cloudfront.net/Prod/events/9/{m}/none/live"]

    out, seen = [], set()
    for base in bases:
        urls = [base]
        if "{m}" in base:
            urls = [base.format(m=mm) for mm in range(1, 13)]
        else:
            # swap the month segment 1..12
            urls = [re.sub(r"(/Prod/events/\d+/)\d+(/none/live)", rf"\g<1>{mm}\g<2>", base)
                    for mm in range(1, 13)]
        for u in urls:
            try:
                data = _get(u)
            except Exception:  # noqa: BLE001
                continue
            for e in (_events(data) or []):
                if e.get("ShowInCalendar") is False:
                    continue
                title = TAGS.sub("", e.get("Title") or e.get("StrippedTitle") or "").strip()
                when = e.get("StartDate")
                if not title or not when:
                    continue
                key = (title, when[:10])
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "title": title,
                    "start": when,
                    "end": e.get("EndDate"),
                    "url": e.get("EventLink") or venue["url"],
                    "location": e.get("Venue") or "David Geffen Hall",
                })
    return out
