import os
import statistics
from collections import defaultdict
from datetime import datetime

import boto3

REGION = "ap-south-1"
TABLE = "SnapScaleImages"
DELIBERATE_WORDS = ("bad", "corrupt", "fake", "toowide", "oversize")
DELIBERATE_IDS = {"f3bb3730-50cd-4465-895b-073db7b8f59b", "test-bad"}
lines = []


def out(text=""):
    print(text)
    lines.append(text)


def load_all():
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    items, kwargs = [], {}
    while True:
        resp = table.scan(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def variants_of(item):
    v = item.get("variants") or {}
    if isinstance(v, list):
        d = {}
        for x in v:
            name = x.get("name") or str(x.get("key", "")).split("/")[-1].split(".")[0]
            d[name] = x
        return d
    return v


def is_deliberate(item):
    name = (item.get("originalFilename") or "").lower()
    return item["imageId"] in DELIBERATE_IDS or any(w in name for w in DELIBERATE_WORDS)


def is_burst(item):
    return "burst" in (item.get("originalFilename") or "").lower()


def seconds(item):
    try:
        a = datetime.fromisoformat(item["uploadedAt"])
        b = datetime.fromisoformat(item["completedAt"])
        return (b - a).total_seconds()
    except (KeyError, ValueError):
        return None


def latency_block(label, items):
    vals = sorted(s for s in (seconds(i) for i in items) if s is not None)
    if not vals:
        out(f"  {label}: no data")
        return
    p95 = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
    out(f"  {label}: n={len(vals)} avg={sum(vals)/len(vals):.2f}s "
        f"median={statistics.median(vals):.2f}s p95={p95:.2f}s "
        f"min={vals[0]:.2f}s max={vals[-1]:.2f}s")


def reduction_block(label, items):
    out(f"  {label}")
    groups = defaultdict(list)
    for it in items:
        orig = int(it["originalSizeBytes"])
        for name, v in variants_of(it).items():
            groups[(it.get("imageFormat", "?"), name)].append((orig, int(v["sizeBytes"])))
    if not groups:
        out("    no data")
    for (fmt, name), pairs in sorted(groups.items()):
        total_o = sum(p[0] for p in pairs)
        total_v = sum(p[1] for p in pairs)
        per_image = [(o - v) / o * 100 for o, v in pairs]
        out(f"    {fmt:5} {name:10} n={len(pairs):3} "
            f"total-bytes reduction={(total_o-total_v)/total_o*100:5.1f}% "
            f"avg per image={sum(per_image)/len(per_image):5.1f}%")


items = load_all()
completed = [i for i in items if i["status"] == "COMPLETED"]
others = [i for i in items if i["status"] != "COMPLETED"]

out("=== 1. Records by status ===")
counts = defaultdict(int)
for i in items:
    counts[i["status"]] += 1
out(f"  total records: {len(items)}")
for s, n in sorted(counts.items()):
    out(f"  {s}: {n}")

out("")
out("=== 2. Every record that is NOT COMPLETED ===")
for i in others:
    tag = "deliberate" if is_deliberate(i) else "NOT on deliberate list"
    out(f"  {i['imageId']} | {i['status']} | attempts={i.get('attempts')} | "
        f"{i.get('originalFilename')} | {tag}")

out("")
out("=== 3. Processing success rate ===")
uploaded = [i for i in items if i["status"] != "PENDING"]
out(f"  Option A (strict): {len(completed)} / {len(uploaded)} = "
    f"{len(completed)/len(uploaded)*100:.2f}%  (all records that got a file)")
valid = completed + [i for i in others if i["status"] != "PENDING" and not is_deliberate(i)]
out(f"  Option B (headline): {len(completed)} / {len(valid)} = "
    f"{len(completed)/len(valid)*100:.2f}%  (valid images only)")

out("")
out("=== 4. Byte reduction (COMPLETED records only) ===")
reduction_block("All completed (burst.jpg dominates: ~200 of the records)", completed)
reduction_block("Without burst records", [i for i in completed if not is_burst(i)])

out("")
out("=== 5. Latency: completedAt - uploadedAt (server side) ===")
latency_block("All completed", completed)
latency_block("Burst records", [i for i in completed if is_burst(i)])
latency_block("Non-burst records", [i for i in completed if not is_burst(i)])
pms = [int(i["processingMs"]) for i in completed if "processingMs" in i]
if pms:
    out(f"  processingMs: avg={sum(pms)/len(pms):.0f} max={max(pms)}")

os.makedirs("docs/test-results", exist_ok=True)
with open("docs/test-results/metrics-summary.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
out("")
out("Saved: docs/test-results/metrics-summary.txt")