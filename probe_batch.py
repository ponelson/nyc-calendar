# Batch discovery probe — finds how each venue serves its data.
from scrape.render import render
import json, re

SITES = [
  ('Blue Note','https://www.bluenotejazz.com/nyc/shows/?calendar_view'),
  ('Birdland','https://www.birdlandjazz.com/calendar/'),
  ('Village Vanguard','https://villagevanguard.com/'),
  ('92Y','https://www.92ny.org/whats-on/calendar'),
  ('Carnegie','https://www.carnegiehall.org/Events#calendar'),
  ('Smalls','https://www.smallslive.com/events/calendar/'),
  ('Harlem Jazz Boxx','https://www.harlemjazzboxx.com/event-calendar'),
  ('54 Below','https://54below.org/calendar/'),
  ('Jazz at Lincoln Center','https://jazz.org/concerts-events/calendar/'),
  ('Met Live Arts','https://www.metmuseum.org/events/calendar?program=Met+Live+Arts'),
  ('Met Opera','https://www.metopera.org/Calendar/?date=2026-10-05&layout=C&categories=On%20Stage'),
  ('NYCB','https://www.nycballet.com/season-and-tickets/calendar'),
  ('NY Phil','https://www.nyphil.org/concerts-tickets/event-calendar'),
  ("Melody's",'https://www.melodyspianobar.com/'),
  ('Broadway (theater.guide)','https://theater.guide/broadway/calendar/'),
]

KEYWORDS = ['trio','quartet','quintet','pm','startdate','start_date','performer',
            'artist','8:00','7:30','event','concert','show','opera']

for name,url in SITES:
    print('='*60)
    print(name)
    print(url)
    try:
        html, payloads = render(url, capture_json=True, scroll=3)
        # JSON APIs the page fetched
        hits=[]
        for p in payloads:
            b=str(p['body']).lower()
            score=sum(1 for k in KEYWORDS if k in b)
            if score>=3 and len(str(p['body']))>500:
                hits.append((len(str(p['body'])), score, p['url']))
        hits.sort(reverse=True)
        print('  JSON feeds found:', len(hits))
        for size,score,u in hits[:4]:
            print(f'    {size:>8}b  score{score}  {u[:88]}')
        # inline data
        print('  __NEXT_DATA__:', '__NEXT_DATA__' in html,
              '| ld+json:', 'application/ld+json' in html,
              '| wp-json:', html.count('wp-json')>0,
              '| tribe(events-cal):', 'tribe-events' in html or 'tribe_events' in html)
    except Exception as e:
        print('  ERR', type(e).__name__, str(e)[:70])
print('='*60)
print('DONE')
