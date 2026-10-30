"""
Algolia, asked directly.

Carnegie Hall and 92NY both paint their calendars from Algolia and both ask for a
small slice: Carnegie ten hits, 92NY the month on screen. The browser shows us the
exact query — index, filters, and the public search-only key the page sends — so we
send it again from Python, straight to Algolia, with two changes:

  * hitsPerPage raised to 1000 (or, if the key refuses that, the page's own size
    walked page by page)
  * any upper date bound in numericFilters / filters pushed out to the horizon

Algolia sits outside the venues' bot walls (DataDome at Carnegie, hCaptcha at 92NY),
so once a query is known it works from CI. Each captured query is saved to
scrape/state/algolia-<venue>.json; when a run can't load the venue page, the saved
query is used instead. The key is the same public search key every visitor's browser
receives.
"""
import json
import os
import re
import time
from urllib.parse import parse_qsl, urlencode, quote, urlsplit

import requests

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


STATE_DIR = os.path.join(os.path.dirname(__file__), "state")


def _creds(p):
    """(app_id, api_key) from a captured request's headers or query string."""
    h = {k.lower(): v for k, v in (p.get("headers") or {}).items()}
    q = {k.lower(): v for k, v in parse_qsl(urlsplit(p["url"]).query)}
    app = h.get("x-algolia-application-id") or q.get("x-algolia-application-id")
    key = h.get("x-algolia-api-key") or q.get("x-algolia-api-key")
    if not app:
        m = re.match(r"https://([a-z0-9]+)-dsn\.algolia\.net", p["url"], re.I)
        app = m.group(1) if m else None
    return app, key


def specs_from(payloads, page_url):
    """Every distinct Algolia query the page made, with what's needed to send it again."""
    out, seen = [], set()
    for p in payloads:
        if "algolia" not in p["url"] or not p.get("post"):
            continue
        try:
            body = json.loads(p["post"])
        except (ValueError, TypeError):
            continue
        app, key = _creds(p)
        if not (app and key):
            continue
        sig = json.dumps(body, sort_keys=True)
        if sig in seen:
            continue
        seen.add(sig)
        parts = urlsplit(p["url"])
        out.append({"endpoint": f"{parts.scheme}://{parts.netloc}{parts.path}",
                    "app": app, "key": key, "body": body, "referer": page_url})
    return out


def save(venue_id, specs):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, f"algolia-{venue_id}.json"), "w") as f:
        json.dump({"saved": time.strftime("%Y-%m-%d"), "specs": specs}, f, indent=1)


def load(venue_id):
    try:
        with open(os.path.join(STATE_DIR, f"algolia-{venue_id}.json")) as f:
            d = json.load(f)
        return d.get("specs") or [], d.get("saved", "?")
    except (OSError, ValueError):
        return [], None


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


def _post(spec, size, page_no):
    body = spec["body"]
    if "requests" in body:
        nb = dict(body)
        nb["requests"] = [_set_size(r, size, page_no) for r in body["requests"]]
    else:
        nb = _set_size(body, size, page_no)
    origin = "/".join(spec["referer"].split("/")[:3])
    try:
        r = requests.post(spec["endpoint"], data=json.dumps(nb), timeout=30, headers={
            "X-Algolia-API-Key": spec["key"], "X-Algolia-Application-Id": spec["app"],
            "Content-Type": "application/json", "Referer": spec["referer"], "Origin": origin,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, None
    if r.status_code != 200:
        return r.status_code, None
    try:
        return 200, r.json()
    except ValueError:
        return "not json", None


def _pages_left(data):
    results = (data.get("results") if isinstance(data, dict) else None) or [data]
    return any(isinstance(r, dict) and (r.get("page", 0) + 1) < r.get("nbPages", 1)
               for r in results)


def query_all(specs):
    """Send each saved query for the whole season. Returns (bodies, notes).
    Algolia sits outside the venue's bot wall, so this works from CI even when the
    venue's own page is behind DataDome or a captcha."""
    out, notes = [], []
    for spec in specs[:3]:
        status, data = _post(spec, 1000, 0)
        if data:
            out.append(data)
            n = 1
            while _pages_left(data) and n < MAX_PAGES:
                status, data = _post(spec, 1000, n)
                if not data:
                    break
                out.append(data)
                n += 1
            notes.append(f"1000/page ok, {n} page(s)")
            continue
        size = _orig_size(spec["body"])
        notes.append(f"1000/page refused ({status}); walking {size}/page")
        for n in range(90):
            status, data = _post(spec, size, n)
            if not data:
                notes.append(f"stopped at page {n} ({status})")
                break
            out.append(data)
            if not _pages_left(data):
                notes.append(f"walked {n + 1} pages")
                break
    return out, notes


def harvest(venue):
    """Render the venue page to catch its Algolia query; fall back to the last query
    saved in scrape/state when the page is walled. Returns (bodies, notes, payloads)."""
    from .render import render, describe
    notes, payloads = [], []
    try:
        _, payloads = render(venue["url"], capture_json=True, scroll=1)
    except Exception as e:  # noqa: BLE001
        notes.append(f"render failed: {type(e).__name__}")
    key = venue.get("state_key", venue["id"])
    specs = specs_from(payloads, venue["url"])
    if specs:
        save(key, specs)
        notes.append(f"captured {len(specs)} query(ies), saved")
    else:
        specs, saved = load(key)
        notes.append(f"no query captured ({describe(payloads, 2)}); "
                     + (f"using query saved {saved}" if specs else
                        "none saved — run once from a home connection: "
                        f"python -m scrape.main --only {venue['id']}"))
    captured = [p["body"] for p in payloads if "algolia" in p["url"] and p.get("body")]
    bodies, more = query_all(specs) if specs else ([], [])
    return captured + bodies, notes + more, payloads


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
