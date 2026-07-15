"""
WordPress.

A large share of this list runs on WordPress — the jazz clubs, the churches, the
historic houses, most small theaters. That's a gift, because WordPress ships a JSON API
whether or not the venue knows it. Two doors:

  1. The Events Calendar plugin (very common) exposes a clean, documented REST endpoint:
         /wp-json/tribe/events/v1/events?per_page=50
     Returns title, start_date, end_date, venue, url. Nothing to parse. Best case.

  2. Plain WordPress exposes every post type at:
         /wp-json/wp/v2/types            -> what post types exist
         /wp-json/wp/v2/<type>?per_page=100
     Village Vanguard, for instance, is WooCommerce + a custom `event` post type. The
     artist name is the post title; the run dates live in the title, the excerpt, or the
     linked ticket products.

Door 2 is where the date parsing gets ugly, because a club that writes "JULY 15 - JULY 20"
in an excerpt is not publishing structured data — it's publishing prose that happens to
be in a JSON envelope. So we parse dates out of text, conservatively, and refuse to guess.
An event we can't date is an event we drop. A wrong date is worse than a missing one.
"""
import re
from datetime import date, datetime

import requests

from .. import fetch

MONTHS = ("january february march april may june july august september "
          "october november december").split()
MONTH_RE = "|".join(m[:3] for m in MONTHS)

# "July 15 - July 20", "JULY 15-20", "Jul 15 – 20, 2026"
RANGE = re.compile(
    rf"\b({MONTH_RE})[a-z]*\.?\s+(\d{{1,2}})\s*(?:[-–—]|through|to)\s*"
    rf"(?:({MONTH_RE})[a-z]*\.?\s+)?(\d{{1,2}})(?:,?\s*(\d{{4}}))?",
    re.I)
SINGLE = re.compile(
    rf"\b({MONTH_RE})[a-z]*\.?\s+(\d{{1,2}})(?:,?\s*(\d{{4}}))?", re.I)

TAGS = re.compile(r"<[^>]+>")


def _mnum(name):
    name = name.lower()[:3]
    return next(i + 1 for i, m in enumerate(MONTHS) if m.startswith(name))


def _year_for(month, day, hint=None):
    """No year given? Assume the next occurrence — venues don't list the past."""
    if hint:
        return int(hint)
    today = date.today()
    y = today.year
    try:
        if date(y, month, day) < today.replace(day=1):
            y += 1
    except ValueError:
        pass
    return y


def dates_from_text(text):
    """Return (start, end) as ISO strings, or (None, None). Conservative by design."""
    text = TAGS.sub(" ", text or "")
    m = RANGE.search(text)
    if m:
        m1, d1, m2, d2, yr = m.groups()
        mo1 = _mnum(m1)
        mo2 = _mnum(m2) if m2 else mo1
        y1 = _year_for(mo1, int(d1), yr)
        y2 = y1 + 1 if mo2 < mo1 else y1
        try:
            return (date(y1, mo1, int(d1)).isoformat(),
                    date(y2, mo2, int(d2)).isoformat())
        except ValueError:
            return None, None
    m = SINGLE.search(text)
    if m:
        mo, d, yr = m.groups()
        mo = _mnum(mo)
        try:
            iso = date(_year_for(mo, int(d), yr), mo, int(d)).isoformat()
            return iso, iso
        except ValueError:
            return None, None
    return None, None


# Post types that plausibly hold events. Everything else is a trap: `milestone` is a
# company history timeline, `audio_playlist` is a podcast, `product` is the gift shop,
# `people` is the staff directory. All of them contain dates. None of them are events.
TYPE_ALLOW = re.compile(
    r"^(tribe_)?(event|events|performance|performances|show|shows|concert|concerts|"
    r"exhibition|exhibitions|program|programs|calendar|production|productions|"
    r"ch_events|mec-events|ai1ec_event)s?$", re.I)

TYPE_DENY = re.compile(
    r"milestone|person|people|staff|board|press|news|article|post|podcast|audio|"
    r"video|playlist|product|shop|donor|annual|report|essay|review|issue|job|"
    r"testimonial|faq|resource|publication", re.I)


def plausible_types(types):
    return [t for t in types if TYPE_ALLOW.match(t) and not TYPE_DENY.search(t)]


def sane(events):
    """Reject a batch that looks like an archive rather than a calendar.

    A venue's event feed points forward. A history timeline points backward. If most
    of what we parsed is in the past, we parsed the wrong thing — and shipping it
    would be worse than shipping nothing, because a wrong date looks authoritative.
    """
    if not events:
        return False
    today = date.today().isoformat()
    future = sum(1 for e in events if (e.get("start") or "")[:10] >= today)
    # A real calendar has upcoming events. An archive has none. We only need a
    # handful of future dates to trust it — a venue legitimately keeps past events
    # in the same feed, so we don't require them to be the majority.
    return future >= 3


def _root(url):
    return "/".join(url.split("/")[:3])


def _json(url, timeout=20):
    r = requests.get(url, timeout=timeout,
                     headers={"User-Agent": fetch.UA, "Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def tribe(root):
    """The Events Calendar REST API. Clean, dated, done."""
    data = _json(f"{root}/wp-json/tribe/events/v1/events?per_page=50")
    out = []
    for e in data.get("events", []):
        out.append({
            "title": e.get("title", ""),
            "start": e.get("start_date"),
            "end": e.get("end_date"),
            "url": e.get("url"),
            "location": (e.get("venue") or {}).get("venue"),
        })
    return out


def posts(root, post_type, default_time=None):
    """Generic custom post type. Dates come out of the text, or the item is dropped."""
    data = _json(f"{root}/wp-json/wp/v2/{post_type}?per_page=100")
    out = []
    for p in data:
        title = TAGS.sub("", (p.get("title") or {}).get("rendered", "")).strip()
        if not title or re.match(r"^(closed|coming soon)", title, re.I):
            continue
        blob = " ".join([
            title,
            (p.get("excerpt") or {}).get("rendered", ""),
            (p.get("content") or {}).get("rendered", "")[:1500],
        ])
        start, end = dates_from_text(blob)
        if not start:
            continue  # undated is dropped, not guessed
        out.append({
            "title": title,
            "start": f"{start}T{default_time}" if default_time else start,
            "end": end,
            "url": p.get("link"),
        })
    return out


def run(venue):
    root = _root(venue["url"])
    mode = venue.get("wp", "auto")

    if mode in ("auto", "tribe"):
        try:
            events = tribe(root)
            if events:
                return events
        except Exception:  # noqa: BLE001
            if mode == "tribe":
                raise

    post_type = venue.get("wp_type", "event")
    events = posts(root, post_type, default_time=venue.get("default_time"))
    if not venue.get("wp_trust") and not sane(events):
        raise RuntimeError(f"wp:{post_type} looks like an archive, not a calendar "
                           f"({len(events)} items, mostly past) — refusing")
    return events


def discover(url):
    """Used by probe.py: what does this WordPress site actually expose?"""
    root = _root(url)
    found = {}
    try:
        n = len(tribe(root))
        if n:
            found["tribe"] = n
    except Exception:  # noqa: BLE001
        pass
    try:
        types = _json(f"{root}/wp-json/wp/v2/types")
        found["types"] = plausible_types(types)
        found["all_types"] = list(types)
    except Exception:  # noqa: BLE001
        pass
    return found
