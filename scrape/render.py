"""
The browser.

For venues that block a plain HTTP client or render listings in JavaScript, we drive a
real Chromium. It executes the page's JS, satisfies bot checks, and hands us a finished
DOM plus every JSON response the page fetched while loading.

Two additions in v2:

* Each captured payload now carries its REQUEST too (method, headers, body). A calendar
  page usually asks its API for one month or one page of ten. Knowing the exact request
  lets an adapter ask again for more, from inside the same page, with the same cookies
  and keys the venue's own code used.

* `after=fn(page, payloads)` runs before the browser closes, so an adapter can make
  those follow-up requests with `page_fetch()`. Returning (html, payloads, extra).
"""
import json
import re

import os

RENDER_TIMEOUT = 30_000
# NYCAL_HEADED=1 opens a visible Chrome window. For venues behind Cloudflare or hCaptcha
# (the Met, 92NY), a real visible browser on a home connection usually passes on its
# own; if a check wants a click, the person at the keyboard can give it one.
HEADED = bool(os.environ.get("NYCAL_HEADED"))
CHALLENGE = ("just a moment", "attention required", "verify you are human", "checking your browser")
SETTLE_MS = 2_500
_JSONISH = re.compile(r"application/json|\+json")

# headers the browser sets itself; passing them to fetch() is refused or pointless
_DROP_HEADERS = {"host", "content-length", "origin", "referer", "user-agent", "cookie",
                 "accept-encoding", "connection"}


def _ctx(browser):
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 1000},
        locale="en-US", timezone_id="America/New_York",
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"),
    )
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return ctx


def clean_headers(h):
    return {k: v for k, v in (h or {}).items()
            if k.lower() not in _DROP_HEADERS and not k.lower().startswith("sec-")
            and not k.startswith(":")}


def page_fetch(page, url, method="GET", headers=None, body=None):
    """fetch() from inside the rendered page. Returns (status, parsed_json_or_None)."""
    js = """async ([u, m, h, b]) => {
        try {
          const r = await fetch(u, {method: m, headers: h || {}, body: b || undefined,
                                     credentials: 'include'});
          return [r.status, await r.text()];
        } catch (e) { return [0, String(e)]; }
    }"""
    status, text = page.evaluate(js, [url, method, clean_headers(headers), body])
    if status != 200:
        return status, None
    try:
        return status, json.loads(text)
    except (ValueError, TypeError):
        return status, None


def _challenged(page):
    try:
        t = (page.title() or "").lower()
        if any(c in t for c in CHALLENGE):
            return True
        return page.locator("iframe[src*='hcaptcha'], iframe[src*='challenges.cloudflare']").count() > 0
    except Exception:  # noqa: BLE001
        return False


def _await_challenge(page, limit_s=120):
    """Give a bot check up to two minutes to clear (by itself, or by a click)."""
    if not _challenged(page):
        return
    print("    ... a bot check is showing in the browser window; it usually clears by itself."
          " If it asks you to click, click it.", flush=True)
    for _ in range(limit_s):
        page.wait_for_timeout(1000)
        if not _challenged(page):
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:  # noqa: BLE001
                pass
            print("    ... cleared.", flush=True)
            return
    print("    ... still blocked after two minutes; moving on.", flush=True)


def render(url, capture_json=False, wait_for=None, scroll=0, after=None):
    from playwright.sync_api import sync_playwright
    payloads = []
    extra = None
    with sync_playwright() as pw:
        args = ["--disable-blink-features=AutomationControlled"]
        if HEADED:
            try:
                browser = pw.chromium.launch(headless=False, channel="chrome", args=args)
            except Exception:  # noqa: BLE001  — no Google Chrome installed; use Chromium
                browser = pw.chromium.launch(headless=False, args=args)
        else:
            browser = pw.chromium.launch(args=args)
        ctx = _ctx(browser)
        page = ctx.new_page()

        if capture_json:
            def on_response(resp):
                try:
                    ctype = resp.headers.get("content-type", "")
                    req = resp.request
                    if req.resource_type not in ("xhr", "fetch"):
                        return
                    if "text/x-component" in ctype:
                        # Next.js server-component / server-action payloads: JSON lines
                        # behind short ids. Kept raw; adapters decode with rsc_objects().
                        payloads.append({"url": resp.url, "body": None, "rsc": resp.text(),
                                         "method": req.method, "headers": dict(req.headers),
                                         "post": req.post_data})
                        return
                    if not _JSONISH.search(ctype):
                        return
                    payloads.append({
                        "url": resp.url,
                        "body": resp.json(),
                        "method": req.method,
                        "headers": dict(req.headers),
                        "post": req.post_data,
                    })
                except Exception:  # noqa: BLE001
                    pass
            page.on("response", on_response)

        page.goto(url, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT)
        if HEADED:
            _await_challenge(page)
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=10_000)
            except Exception:  # noqa: BLE001
                pass
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(SETTLE_MS)

        # lazy-loaded lists: scroll to trigger more fetches
        for _ in range(scroll):
            try:
                page.mouse.wheel(0, 20000)
                page.wait_for_timeout(1500)
            except Exception:  # noqa: BLE001
                break

        if after:
            try:
                extra = after(page, payloads)
            except Exception as e:  # noqa: BLE001
                extra = {"error": f"{type(e).__name__}: {e}"}

        html = page.content()
        browser.close()
    if after:
        return html, payloads, extra
    return html, payloads


def run(venue):
    from .jsonld import extract
    html, payloads = render(venue["url"],
                            capture_json=venue.get("capture", False),
                            wait_for=venue.get("wait_for"),
                            scroll=venue.get("scroll", 0))
    events = extract(html)
    if not events and payloads:
        from .jsonld import _looks_like_event, _to_event, _walk
        nodes = []
        for p in payloads:
            _walk(p["body"], nodes)
        for obj in nodes:
            if _looks_like_event(obj):
                ev = _to_event(obj)
                if ev:
                    events.append(ev)
    return events


def sniff(url):
    html, payloads = render(url, capture_json=True)
    out = [{"url": p["url"], "bytes": len(json.dumps(p["body"]))} for p in payloads]
    return html, out


def rsc_objects(text):
    """Decode a Next.js flight payload ("1:{...}\n2:[...]") into JSON values."""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^[0-9a-zA-Z]+:(.*)$", line)
        if not m:
            continue
        chunk = m.group(1)
        if chunk[:1] in "[{":
            try:
                out.append(json.loads(chunk))
            except ValueError:
                pass
    return out


def describe(payloads, limit=4):
    """One-line summary of what a page fetched — goes into status.json on failure so
    the next fix can be made from the repo instead of from a pasted terminal."""
    bits = []
    for p in payloads[:limit]:
        b = p.get("body")
        if p.get("rsc") is not None:
            bits.append(f"{p.get('method','GET')} {p['url'][:70]} -> rsc[{len(p['rsc'])}]")
            continue
        shape = (f"dict{sorted(b.keys())[:6]}" if isinstance(b, dict)
                 else f"list[{len(b)}]" if isinstance(b, list) else type(b).__name__)
        bits.append(f"{p.get('method','GET')} {p['url'][:70]} -> {shape}")
    return f"{len(payloads)} JSON payloads: " + " | ".join(bits)
