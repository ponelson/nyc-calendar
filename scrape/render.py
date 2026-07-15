"""
The browser.

For venues that block a plain HTTP client or render listings in JavaScript, we drive a
real Chromium. It executes the page's JS, satisfies bot checks, and hands us a finished
DOM plus every JSON response the page fetched while loading.

`scroll` matters for lazy-loaded calendars (Carnegie paginates its Algolia results 10 at
a time as you scroll). When set, we scroll to the bottom repeatedly, letting each batch
fire, and collect them all.
"""
import json
import re

RENDER_TIMEOUT = 30_000
SETTLE_MS = 2_500
_JSONISH = re.compile(r"application/json|\+json")


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


def render(url, capture_json=False, wait_for=None, scroll=0):
    from playwright.sync_api import sync_playwright
    payloads = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"])
        ctx = _ctx(browser)
        page = ctx.new_page()

        if capture_json:
            def on_response(resp):
                try:
                    if not _JSONISH.search(resp.headers.get("content-type", "")):
                        return
                    if resp.request.resource_type not in ("xhr", "fetch"):
                        return
                    payloads.append({"url": resp.url, "body": resp.json()})
                except Exception:  # noqa: BLE001
                    pass
            page.on("response", on_response)

        page.goto(url, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT)
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

        html = page.content()
        browser.close()
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
