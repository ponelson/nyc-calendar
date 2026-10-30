from scrape.render import render
from scrape.jsonld import extract as jsonld_extract
import json, re

# 1. Smalls — inspect the template HTML the ajax returns
print("="*55)
print("SMALLS ajax template")
_, p = render('https://www.smallslive.com/events/calendar/', capture_json=True, scroll=2)
for x in p:
    if 'upcoming-ajax' in x['url']:
        tmpl = x['body'].get('template','')
        print("  template length:", len(tmpl))
        # find artist-ish markup: look for repeated class names near names
        # print first 1200 chars so we can see the structure
        print(tmpl[:1200])
        break
else:
    print("  no ajax captured")

# 2. JSON-LD event check for the render-tier rooms
for name, url in [
    ('54 Below','https://54below.org/calendar/'),
    ('Blue Note','https://www.bluenotejazz.com/nyc/shows/?calendar_view'),
    ('Vanguard','https://villagevanguard.com/'),
    ('Dizzys','https://www.jazz.org/dizzys/'),
]:
    print("="*55)
    print(name, "JSON-LD")
    try:
        html, _ = render(url, scroll=2)
        evs = jsonld_extract(html)
        print("  events in JSON-LD:", len(evs))
        for e in evs[:3]:
            print("   ", (e.get('start') or '?')[:10], '|', (e.get('title') or '?')[:45])
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:50])
print("DONE")
