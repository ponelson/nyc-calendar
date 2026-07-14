"""HTTP layer. Polite, cached, and it never lets one dead venue kill the run."""
import hashlib
import os
import time
import random
import requests

CACHE_DIR = os.environ.get("NYCAL_CACHE", ".cache")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
      "(personal culture calendar; ponelson@gmail.com)")

_session = requests.Session()
_session.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})


def _cache_path(url):
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".html")


def get(url, ttl=3600, timeout=25, retries=2):
    """Return page text, or None. Caches for `ttl` seconds so re-runs during
    development don't hammer anyone's server."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(url)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path, encoding="utf-8") as f:
            return f.read()

    last = None
    for attempt in range(retries + 1):
        try:
            r = _session.get(url, timeout=timeout)
            if r.status_code == 200:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(r.text)
                time.sleep(1.0 + random.random())  # be a good citizen
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        time.sleep(2 ** attempt)

    raise RuntimeError(last or "fetch failed")
