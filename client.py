"""End-to-end SnapScale test: request upload, upload, wait, fetch variants."""
import os
import sys
import time
from datetime import datetime

import requests

API_URL = os.environ["SNAPSCALE_API_URL"].rstrip("/")
HEADERS = {"x-api-key": os.environ["SNAPSCALE_API_KEY"]}


def main(path):
    name = os.path.basename(path)
    content_type = "image/png" if path.lower().endswith(".png") else "image/jpeg"

    t0 = time.time()
    r = requests.post(f"{API_URL}/uploads", headers=HEADERS,
                      json={"fileName": name, "contentType": content_type}, timeout=30)
    r.raise_for_status()
    request_s = time.time() - t0
    info = r.json()
    image_id = info["imageId"]
    print("imageId:", image_id)

    t1 = time.time()
    with open(path, "rb") as f:
        up = requests.post(info["upload"]["url"], data=info["upload"]["fields"],
                           files={"file": (name, f, content_type)}, timeout=120)
    upload_s = time.time() - t1
    print("S3 upload status:", up.status_code)
    if up.status_code not in (200, 201, 204):
        print(up.text)
        sys.exit(1)

    status = None
    item = {}
    polls = 0
    slowest_poll = 0.0
    while time.time() - t0 < 90:
        p0 = time.time()
        item = requests.get(f"{API_URL}/images/{image_id}", headers=HEADERS, timeout=30).json()
        slowest_poll = max(slowest_poll, time.time() - p0)
        polls += 1
        status = item.get("status")
        if status in ("COMPLETED", "FAILED"):
            break
        time.sleep(0.5)

    elapsed = time.time() - t0
    print(f"Final status: {status} (end-to-end {elapsed:.2f} s)")
    print(f"  client timing: create request {request_s:.2f} s, S3 upload {upload_s:.2f} s, "
          f"{polls} polls, slowest poll {slowest_poll:.2f} s")
    if item.get("uploadedAt") and item.get("completedAt"):
        server_s = (datetime.fromisoformat(item["completedAt"])
                    - datetime.fromisoformat(item["uploadedAt"])).total_seconds()
        print(f"  server latency (completedAt - uploadedAt): {server_s:.2f} s")
    print(item)
    if status == "COMPLETED":
        v = requests.get(f"{API_URL}/images/{image_id}/variants", headers=HEADERS, timeout=30).json()
        for variant, data in v["variants"].items():
            print(f"  {variant}: {data['width']}x{data['height']}, {data['sizeBytes']} bytes")


main(sys.argv[1])