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


def replay(page, payloads):
    """Return a list of Algolia response bodies fetched with full page size."""
    out, tried = [], set()
    for p in payloads:
        if "algolia" not in p["url"] or not p.get("post"):
            continue
        try:
            body = json.loads(p["post"])
        except (ValueError, TypeError):
            continue
        sig = (p["url"].split("?")[0], json.dumps(body, sort_keys=True)[:400])
        if sig in tried:
            continue
        tried.add(sig)

        for page_no in range(MAX_PAGES):
            if "requests" in body:
                nb = dict(body)
                # keep only queries that actually ask for hits (skip facet-count probes)
                nb["requests"] = [_mutate_request(r, page_no) for r in body["requests"]]
            else:
                nb = _mutate_request(body, page_no)
            status, data = page_fetch(page, p["url"], "POST", p.get("headers"),
                                      json.dumps(nb))
            if not data:
                break
            out.append(data)
            results = data.get("results") if isinstance(data, dict) else None
            results = results or [data]
            more = any((r.get("page", 0) + 1) < r.get("nbPages", 1) for r in results
                       if isinstance(r, dict))
            if not more:
                break
        if len(out) >= 1 and len(tried) >= 2:
            break
    return out


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
