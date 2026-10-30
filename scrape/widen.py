"""
Ask again for more.

Calendar front-ends request a first batch — "next 20 sets", "this week", "page 1 of
66" — and render more on scroll or click. We don't click. Instead we take the request
the page made and re-send it with its size and date limits pushed out. This module
rewrites a captured request generically: query-string keys, JSON body keys, PostgREST
operator values (lt.2026-11-06) and Range headers.

Returns the rewritten request plus a list of what changed, so a run that changed
nothing says so in status.json instead of failing silently.
"""
import json
import re
from datetime import date, timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

BIG = 500
DAYS_AHEAD = 150
LIMIT_KEYS = {"limit", "per_page", "perpage", "pagesize", "page_size", "size", "take",
              "count", "first", "max", "maxresults", "rows", "num"}
SPAN_KEYS = {"days", "numdays", "num_days", "weeks", "range"}
END_KEYS = {"end", "enddate", "end_date", "to", "until", "before", "dateto", "date_to",
            "endsbefore", "end_time", "endtime", "max_date", "maxdate", "lte", "lt",
            "end_at", "endat", "todate"}
OFFSET_KEYS = {"offset", "skip", "start_index", "startindex"}
ISO = re.compile(r"^(?P<op>(?:lt|lte|lte?)\.)?(?P<d>\d{4}-\d{2}-\d{2})(?P<rest>.*)$")


def _far(rest=""):
    return (date.today() + timedelta(days=DAYS_AHEAD)).isoformat() + rest


def _value(key, val, changed):
    k = key.lower().replace("-", "_")
    s = str(val)
    if k in LIMIT_KEYS and s.isdigit() and int(s) < BIG:
        changed.append(f"{key}:{s}->{BIG}")
        return BIG if isinstance(val, int) else str(BIG)
    if k in SPAN_KEYS and s.isdigit() and int(s) < DAYS_AHEAD:
        changed.append(f"{key}:{s}->{DAYS_AHEAD}")
        return DAYS_AHEAD if isinstance(val, int) else str(DAYS_AHEAD)
    if k in OFFSET_KEYS and s.isdigit() and s != "0":
        changed.append(f"{key}:{s}->0")
        return 0 if isinstance(val, int) else "0"
    m = ISO.match(s)
    if m and (k in END_KEYS or (m.group("op") or "").startswith("lt")):
        new = (m.group("op") or "") + _far(m.group("rest") if "T" in m.group("rest")[:1] else "")
        changed.append(f"{key}:{s[:16]}->{new[:16]}")
        return new
    return val


def _walk(obj, changed):
    if isinstance(obj, dict):
        return {k: (_walk(v, changed) if isinstance(v, (dict, list)) else _value(k, v, changed))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(x, changed) for x in obj]
    return obj


def widen(req):
    """req: captured payload dict (url, method, headers, post). Returns (url, method,
    headers, body, changes)."""
    changed = []
    parts = urlsplit(req["url"])
    q = [(k, _value(k, v, changed)) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    url = urlunsplit(parts._replace(query=urlencode(q, doseq=True)))

    headers = dict(req.get("headers") or {})
    for hk in list(headers):
        if hk.lower() == "range" and re.match(r"^\d+-\d+$", headers[hk]):
            changed.append(f"Range:{headers[hk]}->0-{BIG - 1}")
            headers[hk] = f"0-{BIG - 1}"

    body = req.get("post")
    if body:
        try:
            body = json.dumps(_walk(json.loads(body), changed))
        except (ValueError, TypeError):
            pairs = parse_qsl(body, keep_blank_values=True)
            if pairs:
                body = urlencode([(k, _value(k, v, changed)) for k, v in pairs])
    return url, req.get("method") or "GET", headers, body, changed
