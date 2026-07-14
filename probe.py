#!/usr/bin/env python3
"""
Run this FIRST, and run it before you trust anything in venues.py.

The registry's `strategy` values are educated guesses. This tells you the truth: for
each venue it fetches the page, tries the ICS paths, tries JSON-LD, tries embedded
state, and reports what it actually found.

    python probe.py                 # everything
    python probe.py --cat jazz      # one category
    python probe.py --only carnegie,joyce

Output is a table plus probe-results.json. Venues that come back with events are ready
to enable. Venues that come back empty are either link-only (fine — the calendar links
to them) or worth a custom adapter (only if you'd genuinely miss them).
"""
import argparse
import json
import sys

from scrape import fetch, ics, jsonld
from scrape.normalize import normalize
from scrape.adapters import wordpress
from scrape.venues import VENUES

GREEN, YELLOW, RED, DIM, END = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def probe(v):
    result = {"id": v["id"], "name": v["name"], "cat": v["cat"],
              "url": v["url"], "found": 0, "via": None, "note": ""}

    # 1. iCalendar, if a predictable path exists
    for cand in ics.candidate_urls(v["url"]):
        try:
            text = fetch.get(cand, ttl=24 * 3600)
        except Exception:  # noqa: BLE001
            continue
        if "BEGIN:VEVENT" in text:
            events = normalize(ics.extract(text), v)
            if events:
                result.update(found=len(events), via="ics", ics_url=cand)
                return result

    # 2. JSON-LD / embedded state
    try:
        html = fetch.get(v["url"], ttl=24 * 3600)
    except Exception as e:  # noqa: BLE001
        result["note"] = f"{type(e).__name__}: {e}"
        return result

    events = normalize(jsonld.extract(html), v)
    if events:
        result.update(found=len(events), via="jsonld")
        result["sample"] = _sample(events)
        return result

    # 3. WordPress — the quiet majority. Tries The Events Calendar REST API first,
    #    then every custom post type the site exposes.
    if "wp-content" in html or "wp-json" in html:
        found = wordpress.discover(v["url"])
        if found.get("tribe"):
            result.update(found=found["tribe"], via="wp-tribe",
                          note="set adapter='wordpress', wp='tribe'")
            return result
        for t in found.get("types", []):
            try:
                raw = wordpress.posts(wordpress._root(v["url"]), t)
            except Exception:  # noqa: BLE001
                continue
            events = normalize(raw, v)
            if events:
                result.update(found=len(events), via=f"wp:{t}",
                              note=f"set adapter='wordpress', wp_type='{t}'")
                result["sample"] = _sample(events)
                return result
        result["note"] = "wordpress, but no dated post type"
        return result

    result["note"] = "no structured events in page"
    return result


def _sample(events):
    return [f"{e['date']}  {e['title']}"
            for e in sorted(events, key=lambda e: e["date"])[:3]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat")
    ap.add_argument("--only")
    args = ap.parse_args()

    targets = [v for v in VENUES if v["strategy"] != "link"]
    if args.cat:
        targets = [v for v in targets if v["cat"] == args.cat]
    if args.only:
        want = set(args.only.split(","))
        targets = [v for v in VENUES if v["id"] in want]

    rows = []
    for v in targets:
        r = probe(v)
        rows.append(r)
        if r["found"]:
            color, via = GREEN, r["via"]
        elif r["note"].startswith("no structured"):
            color, via = YELLOW, "—"
        else:
            color, via = RED, "—"
        print(f"{color}{r['found']:>4}{END}  {via:<7} {r['name'][:34]:<34} "
              f"{DIM}{r['note'][:40]}{END}")
        sys.stdout.flush()

    with open("probe-results.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    ok = [r for r in rows if r["found"]]
    ics_ok = [r for r in ok if r["via"] == "ics"]
    print(f"\n{len(ok)}/{len(rows)} venues yield structured events "
          f"({len(ics_ok)} via iCalendar).")
    print("Enable those in scrape/venues.py. For ics hits, copy the ics_url from "
          "probe-results.json and set strategy='ics'.")


if __name__ == "__main__":
    main()
