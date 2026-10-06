# Run the adapters' OWN code path and trace where it loses the data.
from scrape.venues import BY_ID
from scrape.adapters import birdland, ninetytwoy
from scrape import render as R

print("=== BIRDLAND adapter trace ===")
v = BY_ID['birdland']
print("adapter url:", v['url'])
_, payloads = R.render(v['url'], capture_json=True, scroll=2)
ajax = [p for p in payloads if 'admin-ajax' in p['url']]
print("payloads:", len(payloads), "| admin-ajax matches:", len(ajax))
for p in ajax:
    b = p['body']
    rows = b if isinstance(b, list) else (b.get('events') or b.get('data') or [])
    print("  rows via adapter logic:", len(rows) if hasattr(rows,'__len__') else '?',
          "| body type:", type(b).__name__)
    # the adapter's actual extraction
    out = birdland.run(v)
    print("  birdland.run() returned:", len(out))
    break

print("=== 92Y adapter trace ===")
v = BY_ID['92ny_talks']
print("adapter url:", v['url'])
out = ninetytwoy.run(v)
print("  ninetytwoy.run() returned:", len(out))
# trace manually
_, payloads = R.render(v['url'], capture_json=True, scroll=4)
alg = [p for p in payloads if 'algolia.net' in p['url']]
print("  algolia payloads:", len(alg))
for p in alg:
    body = p['body']
    results = body.get('results', [body]) if isinstance(body, dict) else []
    total = sum(len(r.get('hits',[])) for r in results)
    print("  total hits across results:", total)
print("DONE")
