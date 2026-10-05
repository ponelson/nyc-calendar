"""
92NY (92nd Street Y).

Calendar is Algolia-backed. We render to capture the Algolia response (the page sends
the key in headers we can't easily replay), then read its hits. Confirmed fields:
  Title, Prefix, Suffix (combine to full billing), FirstDate (Unix epoch seconds),
  URL, EventMenu ({'lvl0': ['Talks']/['Concerts']...}).

Prefix + Title + Suffix is the real event line, e.g.
  "Recanati-Kaplan Talks — An Evening to Honor Gloria Steinem — With Marlo Thomas…"
"""
from datetime import datetime, timezone

from .. import render


def _cat_from_menu(menu):
    try:
        lvl0 = (menu or {}).get("lvl0") or []
        return (lvl0[0] if lvl0 else "").lower()
    except Exception:  # noqa: BLE001
        return ""


def run(venue):
    _, payloads = render.render(venue["url"], capture_json=True, scroll=4)
    out, seen = [], set()
    for p in payloads:
        if "algolia.net" not in p["url"]:
            continue
        body = p["body"]
        results = body.get("results", [body]) if isinstance(body, dict) else []
        for res in results:
            for h in res.get("hits", []):
                title = (h.get("Title") or "").strip()
                epoch = h.get("FirstDate")
                if not title or not epoch:
                    continue
                try:
                    when = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
                except (ValueError, TypeError, OSError):
                    continue
                prefix = (h.get("Prefix") or "").strip()
                suffix = (h.get("Suffix") or "").strip()
                full = title
                if suffix:
                    full = f"{title} — {suffix}"
                key = (full, when.date().isoformat())
                if key in seen:
                    continue
                seen.add(key)
                url = h.get("URL") or ""
                if url.startswith("/"):
                    url = "https://www.92ny.org" + url
                out.append({
                    "title": full,
                    "start": when.date().isoformat(),
                    "end": None,
                    "url": url or venue["url"],
                    "location": prefix or "92NY",
                })
    return out
