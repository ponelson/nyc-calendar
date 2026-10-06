# Dump a sample record from each confirmed API so we see real field names.
from scrape.render import render
import json

# Direct-fetchable APIs (the page's own calls). We re-hit them via the browser so
# cookies/headers match, then print the structure.
TARGETS = [
  ('Met Opera', 'https://www.metopera.org/Calendar/?date=2026-10-05&layout=C&categories=On%20Stage', 'ace-api/events'),
  ('NY Phil', 'https://www.nyphil.org/concerts-tickets/event-calendar', 'cloudfront.net/Prod/events'),
  ('Carnegie native', 'https://www.carnegiehall.org/Events#calendar', 'GetCalendarPage'),
  ('92Y', 'https://www.92ny.org/whats-on/calendar', 'algolia.net'),
  ('Smalls', 'https://www.smallslive.com/events/calendar/', 'upcoming-ajax'),
  ('Birdland', 'https://www.birdlandjazz.com/calendar/', 'admin-ajax'),
  ('Harlem Jazz Boxx', 'https://www.harlemjazzboxx.com/event-calendar', 'calendarwiz.com/cwapi'),
]

def find_events(obj, depth=0):
    """Return the first list of dict-records that looks like events."""
    if depth > 8: return None
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and len(obj) >= 2:
            keys = set(obj[0].keys())
            if any(k.lower() in ' '.join(keys).lower() for k in ['date','title','name','event','start']):
                return obj
        for x in obj:
            r = find_events(x, depth+1)
            if r: return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = find_events(v, depth+1)
            if r: return r
    return None

for name, url, needle in TARGETS:
    print('='*60)
    print(name)
    try:
        _, payloads = render(url, capture_json=True, scroll=2)
        hit = None
        for p in payloads:
            if needle in p['url']:
                hit = p; break
        if not hit:
            print('  feed not recaptured this run (needle:', needle, ')')
            continue
        evs = find_events(hit['body'])
        if evs:
            print('  event list found,', len(evs), 'records. First record keys:')
            rec = evs[0]
            for k, v in rec.items():
                vs = str(v)[:60].replace('\n',' ')
                print(f'    {k} = {vs}')
        else:
            print('  no event-list found; top-level keys:', list(hit['body'].keys())[:15] if isinstance(hit['body'],dict) else type(hit['body']))
    except Exception as e:
        print('  ERR', type(e).__name__, str(e)[:70])
print('='*60); print('DONE')
