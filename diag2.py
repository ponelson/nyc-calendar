from scrape.render import render
import json

# Birdland
_, p = render('https://www.birdlandjazz.com/calendar/', capture_json=True, scroll=2)
for x in p:
    if 'admin-ajax' in x['url']:
        body = x['body']
        evs = body.get('events', [])
        print('BIRDLAND events type:', type(evs).__name__, '| len/keys:',
              len(evs) if hasattr(evs,'__len__') else '?')
        if isinstance(evs, dict):
            print('  events is a DICT keyed by:', list(evs.keys())[:5])
            firstkey = list(evs.keys())[0] if evs else None
            if firstkey:
                inner = evs[firstkey]
                print('  first group:', firstkey, '->', type(inner).__name__)
                if isinstance(inner, list) and inner:
                    print('  record keys:', list(inner[0].keys()))
                    print(json.dumps(inner[0], indent=2)[:400])
        elif isinstance(evs, list) and evs:
            print('  record keys:', list(evs[0].keys()))
            print(json.dumps(evs[0], indent=2)[:400])
        break

print('='*50)

# 92Y
_, p = render('https://www.92ny.org/whats-on/calendar', capture_json=True, scroll=4)
for x in p:
    if 'algolia' in x['url']:
        res = x['body'].get('results', [{}])[0]
        hits = res.get('hits', [])
        print('92Y hits:', len(hits), '| result keys:', list(res.keys())[:8])
        if hits:
            h = hits[0]
            print('  FirstDate =', repr(h.get('FirstDate')))
            print('  Title =', repr(h.get('Title'))[:50])
            print('  all keys:', list(h.keys())[:20])
        break
print('DONE')
