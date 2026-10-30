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


NOTE = {}


def run(venue):
    html, payloads, extra = render.render(
        venue["url"], capture_json=True, scroll=2, after=algolia.replay)
    bodies = [p["body"] for p in payloads if "algolia" in p["url"]]
    extra = extra if isinstance(extra, dict) else {}
    replayed = extra.get("bodies") or []
    bodies += replayed

    out, seen, menus = [], set(), {}
    for h in algolia.hits(bodies):
        m = _menu(h) or "(none)"
        menus[m] = menus.get(m, 0) + 1
        if not _wanted(h, venue):
            continue
        title = _clean(h.get("Title"))
        epoch = h.get("FirstDate")
        if not title or not epoch:
            continue
        try:
            # 92NY stores New York wall-clock time as if it were UTC: a 7:30 PM talk
            # arrives as 19:30Z. Read it back without converting.
            when = datetime.fromtimestamp(int(float(epoch)), tz=timezone.utc)
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

    days = sorted(e["start"][:10] for e in out)
    NOTE[venue["id"]] = (f"{len(out)} kept {days[0] if days else ''}..{days[-1] if days else ''}; "
                         f"menus seen {dict(sorted(menus.items(), key=lambda x: -x[1])[:8])}; "
                         + " | ".join(extra.get("notes") or [str(extra.get("error", ""))])
                         + "; " + render.describe(payloads, 2))[:700]
    if not out:
        raise RuntimeError(f"no hits; {NOTE.get(venue['id'],'')}")
    return out
