"""
92NY (92nd Street Y).

Algolia-backed calendar. v1 read only the hits the page fetched on load — the month
on screen — so the count fell by ~3 a day all month. v2 replays 92NY's own Algolia
request from inside the page at full size with the date bound pushed out (see
scrape/algolia.py).

Confirmed fields: Title, Prefix, Suffix, FirstDate (epoch seconds), URL,
EventMenu ({'lvl0': ['Talks'] / ['Concerts'] ...}).

Both registry entries (92ny_music, 92ny_talks) use this adapter; each passes `menu`
so a concert isn't listed twice. Hits with no menu go to talks only.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import html as _html
import re

from .. import algolia, render

TAGS = re.compile(r"<[^>]+>")
NY = ZoneInfo("America/New_York")


def _clean(t):
    return TAGS.sub("", _html.unescape(t or "")).strip()


def _menu(h):
    m = h.get("EventMenu") or {}
    try:
        lvl0 = m.get("lvl0") or []
        if isinstance(lvl0, str):
            lvl0 = [lvl0]
        return " ".join(str(x) for x in lvl0).lower()
    except Exception:  # noqa: BLE001
        return ""


def _wanted(h, venue):
    want = [w.lower() for w in venue.get("menu", [])]
    if not want:
        return True
    menu = _menu(h)
    if not menu:
        return venue.get("menu_default", False)
    return any(w in menu for w in want)


def run(venue):
    html, payloads, extra = render.render(
        venue["url"], capture_json=True, scroll=2, after=algolia.replay)
    bodies = [p["body"] for p in payloads if "algolia" in p["url"]]
    replayed = extra if isinstance(extra, list) else []
    bodies += replayed

    out, seen = [], set()
    for h in algolia.hits(bodies):
        if not _wanted(h, venue):
            continue
        title = _clean(h.get("Title"))
        epoch = h.get("FirstDate")
        if not title or not epoch:
            continue
        try:
            when = datetime.fromtimestamp(int(float(epoch)), tz=timezone.utc).astimezone(NY)
        except (ValueError, TypeError, OSError):
            continue
        suffix = _clean(h.get("Suffix"))
        full = f"{title} — {suffix}" if suffix else title
        key = (full.lower(), when.date().isoformat())
        if key in seen:
            continue
        seen.add(key)
        url = h.get("URL") or ""
        if url.startswith("/"):
            url = "https://www.92ny.org" + url
        t = when.strftime("%H:%M")
        out.append({
            "title": full,
            "start": when.strftime("%Y-%m-%d") + (f"T{t}" if t != "00:00" else ""),
            "end": None,
            "url": url or venue["url"],
        })

    if not out:
        why = extra.get("error") if isinstance(extra, dict) else f"replayed {len(replayed)}"
        raise RuntimeError(f"no hits ({why}); " + render.describe(payloads))
    return out
