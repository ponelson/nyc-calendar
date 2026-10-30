"""
Algolia replay.

Carnegie Hall and 92NY both paint their calendars from Algolia, and both ask for a
small slice: Carnegie ten hits, 92NY the month on screen. The browser shows us the
exact request — index, filters, and the search-only key in its headers — so we send it
again from inside the same page with two changes:

  * hitsPerPage raised to 1000 (Algolia's ceiling), paging until nbPages runs out
  * any upper date bound in numericFilters / filters pushed out to the horizon

Everything else (facets, index, sort) stays as the venue wrote it. If the replay fails
for any reason, the adapter still has the original captured hits to fall back on.
"""
import json
import re
import time
from urllib.parse import parse_qsl, urlencode, quote

from .render import page_fetch

HORIZON_DAYS = 240
MAX_PAGES = 6

# field<=1761955200  /  field < 1761955200000.0  /  field:1761 TO 1764
_UPPER = re.compile(r"([\w.]+)\s*(<=|<)\s*(\d{10,13}(?:\.\d+)?)")
_RANGE = re.compile(r"([\w.]+)\s*:\s*(\d{10,13}(?:\.\d+)?)\s+TO\s+(\d{10,13}(?:\.\d+)?)")


def _horizon(sample):
    secs = int(time.time()) + HORIZON_DAYS * 86400
    return str(secs * 1000) if len(sample.split(".")[0]) >= 13 else str(secs)


def _widen(text):
    if not isinstance(text, str):
        return text
    text = _UPPER.sub(lambda m: f"{m.group(1)}{m.group(2)}{_horizon(m.group(3))}", text)
    text = _RANGE.sub(lambda m: f"{m.group(1)}:{m.group(2)} TO {_horizon(m.group(3))}", text)
    return text


def _mutate_request(req, page_no):
    req = dict(req)
    if isinstance(req.get("params"), str):
        pairs = parse_qsl(req["params"], keep_blank_values=True)
        out, seen = [], set()
        for k, v in pairs:
            if k == "hitsPerPage":
                v = "1000"
            elif k == "page":
                v = str(page_no)
            elif k in ("numericFilters", "filters"):
                v = _widen(v)
            out.append((k, v))
            seen.add(k)
        if "hitsPerPage" not in seen:
            out.append(("hitsPerPage", "1000"))
        if "page" not in seen:
            out.append(("page", str(page_no)))
        req["params"] = urlencode(out, quote_via=quote)
    else:
        req["hitsPerPage"] = 1000
        req["page"] = page_no
        for k in ("numericFilters", "filters"):
            if k in req:
                req[k] = json.loads(_widen(json.dumps(req[k])))
    return req


def _creds_to_query(url, headers):
    """Move x-algolia-* credentials from headers into the URL (Algolia accepts both).
    Keeps the replay a CORS 'simple request', the same trick Algolia's own client uses."""
    h = dict(headers or {})
    extra = []
    for k in list(h):
        if k.lower() in ("x-algolia-api-key", "x-algolia-application-id"):
            extra.append((k.lower(), h.pop(k)))
    for k in list(h):
        if k.lower() == "content-type":
            h.pop(k)
    h["content-type"] = "application/x-www-form-urlencoded"
    if extra:
        url += ("&" if "?" in url else "?") + urlencode(extra)
    return url, h


def _orig_size(body):
    reqs = body.get("requests") if isinstance(body, dict) and "requests" in body else [body]
    for r in reqs:
        if isinstance(r, dict):
            if isinstance(r.get("params"), str):
                q = dict(parse_qsl(r["params"]))
                if q.get("hitsPerPage", "").isdigit() and int(q["hitsPerPage"]) > 0:
                    return int(q["hitsPerPage"])
            elif str(r.get("hitsPerPage", "")).isdigit() and int(r["hitsPerPage"]) > 0:
                return int(r["hitsPerPage"])
    return 10


def _set_size(req, size, page_no):
    req = _mutate_request(req, page_no)
    if isinstance(req.get("params"), str):
        req["params"] = re.sub(r"hitsPerPage=\d+", f"hitsPerPage={size}", req["params"])
    else:
        req["hitsPerPage"] = size
    return req


def _send(page, url, headers, body, size, page_no):
    if "requests" in body:
        nb = dict(body)
        nb["requests"] = [_set_size(r, size, page_no) for r in body["requests"]]
    else:
        nb = _set_size(body, size, page_no)
    return page_fetch(page, url, "POST", headers, json.dumps(nb))


def _pages_left(data):
    results = (data.get("results") if isinstance(data, dict) else None) or [data]
    return any(isinstance(r, dict) and (r.get("page", 0) + 1) < r.get("nbPages", 1)
               for r in results)


def replay(page, payloads):
    """Re-send the page's own Algolia query for the whole season.
    Returns {"bodies": [...], "notes": [...]} — notes land in status.json."""
    out, notes, tried = [], [], set()
    posts = [p for p in payloads if "algolia" in p["url"] and p.get("post")]
    gets = [p for p in payloads if "algolia" in p["url"] and not p.get("post")]
    if gets and not posts:
        notes.append(f"algolia via GET only ({gets[0]['url'][:90]}) — not replayed")
    for p in posts:
        try:
            body = json.loads(p["post"])
        except (ValueError, TypeError):
            notes.append("algolia body not JSON")
            continue
        sig = json.dumps(body, sort_keys=True)[:400]
        if sig in tried:
            continue
        tried.add(sig)
        url, headers = _creds_to_query(p["url"], p.get("headers"))

        # 1. one big page
        status, data = _send(page, url, headers, body, 1000, 0)
        if data:
            out.append(data)
            notes.append(f"1000/page ok")
            n = 1
            while _pages_left(data) and n < MAX_PAGES:
                status, data = _send(page, url, headers, body, 1000, n)
                if not data:
                    break
                out.append(data)
                n += 1
            continue
        # 2. the page's own size, walked page by page
        size = _orig_size(body)
        notes.append(f"1000/page refused ({status}); walking {size}/page")
        for n in range(90):
            status, data = _send(page, url, headers, body, size, n)
            if not data:
                notes.append(f"stopped at page {n} ({status})")
                break
            out.append(data)
            if not _pages_left(data):
                notes.append(f"walked {n + 1} pages")
                break
        if len(tried) >= 3:
            break
    if not posts and not gets:
        notes.append("no algolia request captured")
    return {"bodies": out, "notes": notes}


def hits(bodies):
    """Every hit from a list of Algolia responses (single or multi-query shape)."""
    for b in bodies:
        if not isinstance(b, dict):
            continue
        for res in (b.get("results") or [b]):
            if isinstance(res, dict):
                for h in res.get("hits", []) or []:
                    if isinstance(h, dict):
                        yield h
