"""
Nightly run.

Writes two files:

  docs/data/events.json  — what the calendar reads.
  docs/data/status.json  — how each venue did last night.

status.json is the point. Scrapers rot silently: a venue redesigns, the adapter
returns zero events, and the calendar just quietly shows an empty February. So every
run records a per-venue count, error, and a note on what the adapter actually saw.

Carry-forward (v2.2): when a venue fails, its last good listings that are still in the
future are kept, and status.json says how old they are. A bot wall or a bad night no
longer blanks a venue. It also lets a venue that only answers home connections (the
Met) be refreshed from a laptop now and then and stay on the calendar in between.

`--only` runs merge into the existing files instead of replacing them, so a local
refresh of one venue leaves everything else as it was.
"""
import argparse
import importlib
import json
import os
import sys
import traceback
from datetime import date, datetime, timezone

from . import fetch, ics, jsonld, render
from .normalize import normalize
from .venues import VENUES, scrapable

OUT_DIR = os.environ.get("NYCAL_OUT", "docs/data")


def _run_venue(v):
    strategy = v["strategy"]

    if strategy == "custom":
        mod = importlib.import_module(f".adapters.{v['adapter']}", __package__)
        return mod.run(v)

    if strategy == "render":
        return render.run(v)

    if strategy == "ics":
        text = fetch.get(v["ics_url"], ttl=6 * 3600)
        return ics.extract(text)

    if strategy in ("jsonld", "rss"):
        html = fetch.get(v["url"], ttl=6 * 3600)
        events = jsonld.extract(html)
        if not events and v.get("also"):
            for extra in v["also"]:
                events += jsonld.extract(fetch.get(extra, ttl=6 * 3600))
        return events

    return []


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated venue ids")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()

    ev_path = os.path.join(args.out, "events.json")
    st_path = os.path.join(args.out, "status.json")
    prev_events = _load(ev_path, {}).get("events", [])
    prev_status = {s["id"]: s for s in _load(st_path, {}).get("venues", [])}
    prev_gen = _load(st_path, {}).get("generated", "")[:10]
    today = date.today().isoformat()

    targets = scrapable()
    if args.only:
        want = set(args.only.split(","))
        targets = [v for v in VENUES if v["id"] in want]
    target_ids = {v["id"] for v in targets}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_events, status = [], []
    for v in targets:
        entry = {"id": v["id"], "name": v["name"], "cat": v["cat"],
                 "strategy": v["strategy"], "count": 0, "error": None}
        try:
            raw = _run_venue(v)
            if v["strategy"] == "custom":
                mod = importlib.import_module(f".adapters.{v['adapter']}", __package__)
                note = getattr(mod, "NOTE", {}).get(v["id"])
                if note:
                    entry["note"] = note
            events = normalize(raw, v)
            all_events.extend(events)
            entry["count"] = len(events)
            if events:
                entry["last_ok"] = now
            else:
                entry["error"] = "no events parsed"
            print(f"  {v['id']:<22} {len(events):>4}  {v['strategy']}")
        except Exception as e:  # noqa: BLE001
            entry["error"] = f"{type(e).__name__}: {e}"[:900]
            print(f"  {v['id']:<22}  ERR  {entry['error'][:160]}", file=sys.stderr)
            if os.environ.get("NYCAL_DEBUG"):
                traceback.print_exc()

        if not entry["count"]:
            kept = [e for e in prev_events if e.get("src") == v["id"] and e["date"] >= today]
            if kept:
                all_events.extend(kept)
                entry["count"] = len(kept)
                entry["carried"] = True
                entry["last_ok"] = prev_status.get(v["id"], {}).get("last_ok") or prev_gen
                print(f"  {v['id']:<22} {len(kept):>4}  carried forward from {entry['last_ok'][:10]}")
        status.append(entry)

    if args.only:
        # merge: everything not re-run this time stays exactly as it was
        all_events += [e for e in prev_events
                       if e.get("src") not in target_ids and e["date"] >= today]
        status += [s for vid, s in prev_status.items() if vid not in target_ids]
        order = {v["id"]: i for i, v in enumerate(VENUES)}
        status.sort(key=lambda s: order.get(s["id"], 999))

    all_events.sort(key=lambda e: (e["date"], e["time"] or "23:59", e["venue"]))

    os.makedirs(args.out, exist_ok=True)
    with open(ev_path, "w", encoding="utf-8") as f:
        json.dump({"generated": now, "count": len(all_events),
                   "events": all_events}, f, indent=0)

    healthy = sum(1 for s in status if s["count"] > 0)
    with open(st_path, "w", encoding="utf-8") as f:
        json.dump({"generated": now, "healthy": healthy,
                   "total": len(status), "venues": status}, f, indent=2)

    print(f"\n{len(all_events)} events from {healthy}/{len(status)} venues -> {args.out}")
    carried = [s["name"] for s in status if s.get("carried")]
    if carried:
        print("carried forward: " + ", ".join(carried))
    dark = [s["name"] for s in status if s["count"] == 0]
    if dark:
        print("dark: " + ", ".join(dark))


if __name__ == "__main__":
    main()
