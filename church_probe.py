from scrape.render import render
from scrape.jsonld import extract as jsonld_extract
import json

CHURCHES = [
    ('Trinity Wall Street','https://trinitywallstreet.org/music-arts'),
    ('St. John the Divine','https://www.stjohndivine.org/calendar'),
    ('St. Ignatius Loyola (SMSS)','https://www.smssconcerts.org/'),
    ('St. Luke in the Fields','https://stlukeinthefields.org/music/'),
    ('Corpus Christi (MB1800)','https://www.corpuschristinyc.org/music-before-1800'),
    ('St. Bartholomew','https://stbarts.org/music/'),
    ('Church of the Intercession','https://www.intercessionnyc.org/'),
]

KW = ['concert','recital','evensong','bach','mass','choir','organ','pm','startdate','start_date','event']

for name, url in CHURCHES:
    print('='*55)
    print(name)
    try:
        html, payloads = render(url, capture_json=True, scroll=3)
        # JSON feeds
        feeds=[]
        for p in payloads:
            b=str(p['body']).lower()
            score=sum(1 for k in KW if k in b)
            if score>=3 and len(str(p['body']))>800:
                feeds.append((len(str(p['body'])),score,p['url']))
        feeds.sort(reverse=True)
        print('  JSON feeds:', len(feeds))
        for sz,sc,u in feeds[:3]:
            print(f'    {sz:>8}b score{sc} {u[:80]}')
        # JSON-LD events
        evs = jsonld_extract(html)
        print('  JSON-LD events:', len(evs))
        for e in evs[:2]:
            print('    ', (e.get('start') or '?')[:10], '|', (e.get('title') or '?')[:40])
        # platform hints
        print('  wp-json:', html.count('wp-json')>0, '| tribe:', 'tribe' in html.lower(), '| squarespace:', 'squarespace' in html.lower())
    except Exception as e:
        print('  ERR', type(e).__name__, str(e)[:55])
print('DONE')
