"""
NYC Jazz Guide (nycjazz.guide) — one source for the jazz rooms.

The clubs' own sites carry nothing machine-readable (Vanguard, Blue Note, Smoke,
Dizzy's), or block cloud IPs, or show one month at a time (Birdland). nycjazz.guide
aggregates all of them, artist by artist and set by set, refreshed hourly. Its venue
pages are client-rendered — the HTML says "Loading…" and the schedule arrives as JSON
after hydration — so we render each venue page and read what it fetches.

Field names are not hard-coded. The reader walks every JSON object the page received
and takes anything carrying a date plus a performer/title, preferring performer-like
keys (artist, headliner, performer) over generic ones (title, name). Schema.org Event
markup in the rendered DOM is the second door. If both come up empty, the error that
lands in status.json describes exactly what the page fetched, so the next fix can be
made from the repo.

Registry entries set `guide=<slug>`; slugs confirmed from the guide's own directory:
village_vanguard, blue_note, birdland, smoke_jazz_club, dizzys_club_lincoln_center,
smalls, mezzrow, zinc_bar.
"""
import html as _html
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .. import render
from ..jsonld import _walk, extract as jsonld_extract

GUIDE = "https://www.nycjazz.guide/venues/{slug}/events"
NY = ZoneInfo("America/New_York")

PERFORMER_KEYS = ("artist", "artist_name", "artistName", "headliner", "headliner_name",
                  "performer", "performers", "act", "band", "band_name", "leader")
TITLE_KEYS = ("title", "name", "event_name", "eventName", "show_name", "showName")
DATE_KEYS = ("start", "startDate", "start_date", "startTime", "start_time", "starts_at",
             "startsAt", "datetime", "dateTime", "date_time", "show_time", "showTime",
             "date", "show_date", "showDate", "event_date", "eventDate")
TIME_KEYS = ("time", "set_time", "setTime", "showtime", "set_times", "setTimes")
URL_KEYS = ("ticket_url", "ticketUrl", "tickets_url", "ticketsUrl", "ticket_link",
            "url", "link", "href", "permalink")
VENUE_KEYS = ("venue", "venue_name", "venueName", "venue_slug", "venueSlug", "venue_id",
              "venueId", "club", "location")

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")
CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m", re.I)
TAGS = re.compile(r"<[^>]+>")


def _text(v):
    if isinstance(v, str):
        return re.sub(r"\s+", " ", TAGS.sub("", _html.unescape(v))).strip()
    if isinstance(v, dict):
        for k in ("name", "title", "display_name", "displayName"):
            if isinstance(v.get(k), str):
                return _text(v[k])
    if isinstance(v, list) and v:
        names = [_text(x) for x in v[:3]]
        names = [n for n in names if n]
        return " / ".join(names)
    return ""


def _when(v):
    """Return (YYYY-MM-DD, HH:MM or '') in New York time, or (None, None)."""
    if isinstance(v, (int, float)) and v > 1e9:
        secs = v / 1000 if v > 1e12 else v
        d = datetime.fromtimestamp(secs, tz=timezone.utc).astimezone(NY)
        return d.date().isoformat(), d.strftime("%H:%M")
    if not isinstance(v, str) or not ISO.match(v):
        return None, None
    s = v.strip().replace("Z", "+00:00").replace(" ", "T")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return v[:10], ""
    if d.tzinfo:
        d = d.astimezone(NY)
    has_time = "T" in s
    return d.date().isoformat(), (d.strftime("%H:%M") if has_time else "")


def _clock(s):
    m = CLOCK.search(s or "")
    if not m:
        return ""
    h, mn, ap = int(m.group(1)), m.group(2) or "00", m.group(3).lower()
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mn}"


def _other_venue(obj, venue):
    """True if this object names a different club (guide pages may list neighbours)."""
    want = {venue["guide"].replace("_", " ").lower(), venue["name"].lower()}
    for k in VENUE_KEYS:
        if k not in obj:
            continue
        v = obj[k]
        label = (_text(v) or (v.get("slug") if isinstance(v, dict) else "") or str(v)).lower()
        label = label.replace("_", " ").replace("-", " ")
        if not label or label.isdigit():
            continue
        if not any(w in label or label in w for w in want):
            return True
    return False


def _from_json(payloads, venue):
    nodes = []
    for p in payloads:
        if p.get("rsc") is not None:
            for obj in render.rsc_objects(p["rsc"]):
                _walk(obj, nodes)
        elif p.get("body") is not None:
            _walk(p["body"], nodes)
    rows = []
    for obj in nodes:
        if not isinstance(obj, dict):
            continue
        day = t = None
        for k in DATE_KEYS:
            if k in obj:
                day, t = _when(obj[k])
                if day:
                    break
        if not day:
            continue
        title = ""
        for k in PERFORMER_KEYS + TITLE_KEYS:
            if k in obj:
                title = _text(obj[k])
                if title and title.lower() != venue["name"].lower():
                    break
                title = ""
        if not title or len(title) < 2:
            continue
        if _other_venue(obj, venue):
            continue
        if not t:
            for k in TIME_KEYS:
                if k in obj:
                    t = _clock(_text(obj[k]) or str(obj[k]))
                    if t:
                        break
        url = ""
        for k in URL_KEYS:
            if isinstance(obj.get(k), str) and obj[k].startswith(("http", "/")):
                url = obj[k]
                break
        rows.append((title, day, t or "", url))
    return rows


NOTE = {}
BASE = "https://www.nycjazz.guide"

# The venue page calls /api/events/count?venues=<slug>; the list itself is rendered on
# the server. These are the sibling routes worth asking for, in order. Whatever answers
# is logged in status.json either way.
CANDIDATES = (
    "/api/events?venues={slug}&limit=500",
    "/api/events?venues={slug}",
    "/api/events?venue={slug}&limit=500",
    "/api/venues/{slug}/events?limit=500",
    "/api/venues/{slug}/events",
)
MORE_LABEL = re.compile(r"(load|show|see|view)\s+(more|all|later)|more\s+(shows|events|dates)|next\s+(week|page)", re.I)


def _shape(data):
    if isinstance(data, list):
        return f"list[{len(data)}]"
    if isinstance(data, dict):
        return "dict" + str(sorted(data.keys())[:5])
    return type(data).__name__


def _more(venue):
    from .. import widen as W
    slug = venue["guide"]

    def after(page, payloads):
        got, notes = [], []
        # 1. sibling API routes, asked from inside the guide's own page
        for path in CANDIDATES:
            url = BASE + path.format(slug=slug)
            status, data = render.page_fetch(page, url)
            rows = _from_json([{"url": url, "body": data}], venue) if data is not None else []
            notes.append(f"{path.format(slug='*')}:{status}:{_shape(data)}:{len(rows)}rows")
            if rows:
                got.append({"url": url, "body": data})
                # page onward if the route paginates
                for n in range(2, 12):
                    nxt = url + ("&" if "?" in url else "?") + f"page={n}"
                    st2, d2 = render.page_fetch(page, nxt)
                    r2 = _from_json([{"url": nxt, "body": d2}], venue) if d2 is not None else []
                    if not r2 or set(r2) <= set(rows):
                        break
                    rows += r2
                    got.append({"url": nxt, "body": d2})
                notes.append(f"paged to {len(rows)} rows")
                break
        # 2. any captured request that carried shows, widened
        for p in payloads:
            if p.get("body") is None or not _from_json([p], venue):
                continue
            url, method, headers, body, changes = W.widen(p)
            if changes:
                status, data = render.page_fetch(page, url, method, headers, body)
                notes.append(f"widen {status} {' '.join(changes)}")
                if data is not None:
                    got.append({"url": url, "body": data})
        # 3. a "load more" control, found by its visible label, pressed until it's gone
        clicks = 0
        if not got:
            for _ in range(15):
                try:
                    btn = page.get_by_role("button", name=MORE_LABEL).first
                    if not btn.is_visible(timeout=1500):
                        break
                    btn.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    clicks += 1
                except Exception:  # noqa: BLE001
                    break
            notes.append(f"load-more clicks:{clicks}")
        return {"payloads": got, "notes": notes}
    return after


def run(venue):
    url = GUIDE.format(slug=venue["guide"])
    html, payloads, extra = render.render(url, capture_json=True, scroll=3, after=_more(venue))
    extra = extra if isinstance(extra, dict) else {}
    found = extra.get("payloads") or []

    rows = _from_json(payloads + found, venue)
    src = "api" if rows else ""
    ld = []
    for e in jsonld_extract(html):     # final DOM, after any load-more clicks
        day, t = _when(e.get("start"))
        if day and e.get("title"):
            ld.append((_text(e["title"]), day, t or "", e.get("url") or ""))
    if ld:
        rows += ld
        src = (src + "+ld") if src else "ld"

    # one entry per act per night; keep the earliest set time
    best = {}
    for title, day, t, link in rows:
        k = (title.lower(), day)
        if k not in best or (t and (not best[k][2] or t < best[k][2])):
            best[k] = (title, day, t, link)

    out = []
    for title, day, t, link in best.values():
        if link.startswith("/"):
            link = BASE + link
        out.append({
            "title": title,
            "start": f"{day}T{t}" if t else day,
            "end": None,
            "url": link or url,
        })
    days = sorted({r[1] for r in rows})
    rsc = sum(1 for p in payloads if p.get("rsc") is not None)
    NOTE[venue["id"]] = (f"{len(out)} acts {days[0] if days else ''}..{days[-1] if days else ''} via {src or 'nothing'}; "
                         + " | ".join(extra.get("notes") or [str(extra.get("error", ""))])
                         + f"; rsc payloads:{rsc}; captured: " + render.describe(payloads, 4))[:900]
    if not out:
        raise RuntimeError("nycjazz.guide: nothing event-shaped; " + NOTE[venue["id"]])
    return out
