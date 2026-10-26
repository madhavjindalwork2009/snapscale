"""SnapScale burst test: upload the same small JPEG 100 times, no status polling."""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

API_URL = os.environ["SNAPSCALE_API_URL"].rstrip("/")
HEADERS = {"x-api-key": os.environ["SNAPSCALE_API_KEY"]}
PATH = "samples/burst.jpg"
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 100

with open(PATH, "rb") as f:
    DATA = f.read()


def one(i):
    name = f"burst-{i:03d}.jpg"
    r = None
    for _ in range(3):
        r = requests.post(f"{API_URL}/uploads", headers=HEADERS,
                          json={"fileName": name, "contentType": "image/jpeg"}, timeout=30)
        if r.status_code == 429:
            time.sleep(2)
            continue
        break
    if not r.ok:
        return i, None, f"create failed {r.status_code}"
    info = r.json()
    up = requests.post(info["upload"]["url"], data=info["upload"]["fields"],
                       files={"file": (name, DATA, "image/jpeg")}, timeout=120)
    return i, info["imageId"], up.status_code


start = datetime.now(timezone.utc)
t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(one, range(COUNT)))
elapsed = time.time() - t0
end = datetime.now(timezone.utc)

ok = [r for r in results if r[2] in (200, 201, 204)]
bad = [r for r in results if r[2] not in (200, 201, 204)]
print(f"Burst start (UTC): {start.isoformat()}")
print(f"Burst end   (UTC): {end.isoformat()}")
print(f"Requested: {COUNT}, uploaded OK: {len(ok)}, failed: {len(bad)}")
print(f"Total time to send everything: {elapsed:.1f} s")
for r in bad:
    print("FAILED:", r)

with open("docs/test-results/test7-burst-ids.txt", "w") as out:
    for r in ok:
        out.write(r[1] + "\n")
print("Saved", len(ok), "image ids to docs/test-results/test7-burst-ids.txt")