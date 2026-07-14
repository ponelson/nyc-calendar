"""
Nightly run.

Writes two files:

  docs/data/events.json  — what the calendar reads.
  docs/data/status.json  — how each venue did last night.

status.json is the point. Scrapers rot silently: a venue redesigns, the adapter
returns zero events, and the calendar just quietly shows an empty February. So every
run records a per-venue count and error, and the front end surfaces anything that has
gone dark. A scraper you can't audit is worse than no scraper.
"""
import argparse
import importlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone

from . import fetch, ics, jsonld
from .normalize import normalize
from .venues import VENUES, scrapable

OUT_DIR = os.environ.get("NYCAL_OUT", "docs/data")


def _run_venue(v):
    strategy = v["strategy"]

    if strategy == "custom":
        mod = importlib.import_module(f".adapters.{v['adapter']}", __package__)
        return mod.run(v)

    if strategy == "ics":
        text = fetch.get(v["ics_url"], ttl=6 * 3600)
        return ics.extract(text)

    if strategy in ("jsonld", "rss"):
        html = fetch.get(v["url"], ttl=6 * 3600)
        events = jsonld.extract(html)
        # if a venue also has a listings sub-path, follow it once
        if not events and v.get("also"):
            for extra in v["also"]:
                events += jsonld.extract(fetch.get(extra, ttl=6 * 3600))
        return events

    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated venue ids")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()

    targets = scrapable()
    if args.only:
        want = set(args.only.split(","))
        targets = [v for v in VENUES if v["id"] in want]

    all_events, status = [], []
    for v in targets:
        entry = {"id": v["id"], "name": v["name"], "cat": v["cat"],
                 "strategy": v["strategy"], "count": 0, "error": None}
        try:
            raw = _run_venue(v)
            events = normalize(raw, v)
            all_events.extend(events)
            entry["count"] = len(events)
            if not events:
                entry["error"] = "no events parsed"
            print(f"  {v['id']:<22} {len(events):>4}  {v['strategy']}")
        except Exception as e:  # noqa: BLE001
            entry["error"] = f"{type(e).__name__}: {e}"
            print(f"  {v['id']:<22}  ERR  {entry['error']}", file=sys.stderr)
            if os.environ.get("NYCAL_DEBUG"):
                traceback.print_exc()
        status.append(entry)

    all_events.sort(key=lambda e: (e["date"], e["time"] or "23:59", e["venue"]))

    os.makedirs(args.out, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with open(os.path.join(args.out, "events.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": now, "count": len(all_events),
                   "events": all_events}, f, indent=0)

    healthy = sum(1 for s in status if s["count"] > 0)
    with open(os.path.join(args.out, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": now, "healthy": healthy,
                   "total": len(status), "venues": status}, f, indent=2)

    print(f"\n{len(all_events)} events from {healthy}/{len(status)} venues -> {args.out}")

    dark = [s["name"] for s in status if s["count"] == 0]
    if dark:
        print("dark: " + ", ".join(dark))


if __name__ == "__main__":
    main()
