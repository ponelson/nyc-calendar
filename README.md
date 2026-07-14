# NYC Culture Calendar

A single page for dance, classical, opera, talks, theater, Broadway, museums, galleries,
jazz rooms, historic houses, and the sites that open once a year. Scraped nightly where
the venue publishes machine-readable listings, linked out where it doesn't.

Live at `https://ponelson.github.io/nyc-culture-calendar/` once Pages is on.

---

## What this actually does

There is no feed that aggregates New York City Ballet, Bargemusic, Mmuseumm, and Hart
Island. So this isn't an aggregator — it's a harvester with an honest failure mode.

**Three sources feed the calendar:**

1. **The nightly scrape.** `scrape/main.py` visits every enabled venue and reads
   structured event data out of the page. It writes `docs/data/events.json`.
2. **Recurring anchors**, defined in the page itself — Village Vanguard's Monday
   orchestra, Bach at One on Thursdays, Evensong on Sundays. These are rules, not rows,
   so they render for any month, forever. Each is labeled *confirm* because a standing
   program is not a guarantee.
3. **Events you add**, saved locally in the browser. The scrape never overwrites them.

**Two things it deliberately doesn't do:**

- It does not parse CSS selectors. Selector scraping across 130 venues is a part-time
  job you did not ask for. This reads JSON-LD (the schema.org data venues publish for
  Google) and embedded Next.js state. When a venue redesigns, structured data usually
  survives; a `div.event-card__title` never does.
- It does not put a Broadway show in all 300 cells of its run. Runs of two weeks or
  less expand day by day. Longer runs — gallery shows, open-ended Broadway — collapse to
  **Opens** and **Final day**, which are the only two dates you can act on anyway.

---

## Setup

```bash
git clone https://github.com/ponelson/nyc-culture-calendar
cd nyc-culture-calendar
pip install -r requirements.txt
```

### Step one: probe. Do this before anything else.

```bash
python probe.py
```

`scrape/venues.py` contains 155 venues, and its `strategy` field is a **guess**. The
probe replaces guesses with facts. For each venue it tries the standard iCalendar paths,
then JSON-LD, then embedded state, and prints what it actually found:

```
  47  jsonld  Carnegie Hall
  22  ics     Roulette
   0  —       Café Carlyle          no structured events in page
```

Expect somewhere between a third and a half of the list to come back green. That's the
real yield, and it's fine — a green Carnegie, Joyce, BAM, City Center, Public, 92NY,
Zwirner, and Gagosian covers most of what you'd actually go to.

Results land in `probe-results.json`.

### Step two: act on the probe

- **Green via `ics`** — best case. In `venues.py`, set `strategy="ics"` and add
  `ics_url="..."` from the probe results.
- **Green via `jsonld`** — leave it. Already enabled.
- **Empty** — decide. Either flip `enabled=False` and let the calendar link out (right
  answer for Mmuseumm, Hart Island, Café Carlyle — announcement-driven places you'd want
  an email alert for, not a scraper), or write a custom adapter if you'd genuinely miss
  it. `scrape/adapters/broadway.py` is the model.

### Step three: run it

```bash
python -m scrape.main                    # everything
python -m scrape.main --only joyce,bam   # one venue while you debug
NYCAL_DEBUG=1 python -m scrape.main      # full tracebacks
```

Open `docs/index.html` in a browser. It reads `docs/data/events.json`.

### Step four: turn on the nightly job

Push, then in repo settings:

- **Pages** → source: *Deploy from a branch*, branch `main`, folder `/docs`.
- **Actions** → *General* → Workflow permissions → **Read and write**. Without this the
  bot can't commit the updated JSON.

`.github/workflows/update.yml` runs at 05:00 ET, scrapes, and commits only if the data
changed. There's a manual trigger too.

---

## Scrapers rot. This one tells you.

Every run writes `docs/data/status.json` with a per-venue count. The page shows
**"1,240 listings · 47 of 63 venues reporting · 16 dark"** — click *dark* and you get
the list of what stopped working and why.

This is the whole reason to trust the thing. The failure mode of a silent scraper isn't
an error message, it's an empty February that you assume is an empty February.

---

## Layout

```
scrape/
  venues.py       the registry — 155 venues, category, URL, strategy
  fetch.py        polite HTTP: cache, retry, one-second gap between requests
  jsonld.py       schema.org extraction + Next.js state duck-typing
  ics.py          iCalendar parser
  normalize.py    → {date, time, title, venue, cat, url}; run collapsing lives here
  main.py         the nightly run
  adapters/
    broadway.py   keeps only your seven houses; emits open/close, not 8 shows a week
probe.py          find out what's actually readable
docs/
  index.html      the calendar
  data/           events.json, status.json — written by the scrape
```

## Things worth adding later

- **Alerts, not listings**, for the scarce stuff: Green-Wood catacombs, OHNY, the Ellis
  Island hard hat tour, North Brother. These sell out in an hour and a nightly calendar
  is the wrong instrument. A watcher that diffs those five pages and emails you is right.
- **An `.ics` export** so the calendar subscribes into Apple Calendar.
- **A NYCB/ABT talk filter** — already stubbed via `exclude=[...]` in the registry.
