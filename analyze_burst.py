"""Summarise the burst test from DynamoDB (read-only)."""
from datetime import datetime

import boto3

table = boto3.resource("dynamodb", region_name="ap-south-1").Table("SnapScaleImages")

with open("docs/test-results/test7-burst-ids.txt") as f:
    run2_ids = {line.strip() for line in f if line.strip()}

items, kwargs = [], {
    "FilterExpression": "begins_with(originalFilename, :p)",
    "ExpressionAttributeValues": {":p": "burst-"},
}
while True:
    resp = table.scan(**kwargs)
    items += resp["Items"]
    if "LastEvaluatedKey" not in resp:
        break
    kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def ts(s):
    return datetime.fromisoformat(s) if s else None


groups = {"run2 (official, 100 ids saved)": [], "run1 (accidental repeat)": [], "other (3-upload check)": []}
for it in items:
    if it["imageId"] in run2_ids:
        groups["run2 (official, 100 ids saved)"].append(it)
    elif "2026-10-26T14:02" <= it["createdAt"] < "2026-10-26T14:04":
        groups["run1 (accidental repeat)"].append(it)
    else:
        groups["other (3-upload check)"].append(it)

for name, g in groups.items():
    print(f"\n== {name}: {len(g)} records")
    statuses = {}
    for it in g:
        statuses[it["status"]] = statuses.get(it["status"], 0) + 1
    print("  statuses:", statuses)
    print("  max attempts:", max((int(it.get("attempts", 0)) for it in g), default=0))
    done = [it for it in g if it["status"] == "COMPLETED"]
    if done:
        lat = [(ts(i["completedAt"]) - ts(i["uploadedAt"])).total_seconds() for i in done]
        pms = [int(i["processingMs"]) for i in done]
        first_created = min(ts(i["createdAt"]) for i in g)
        last_done = max(ts(i["completedAt"]) for i in done)
        print(f"  first createdAt:  {first_created.isoformat()}")
        print(f"  last completedAt: {last_done.isoformat()}")
        print(f"  wall-clock first create -> last completion: {(last_done - first_created).total_seconds():.1f} s")
        print(f"  latency completedAt-uploadedAt: avg {sum(lat)/len(lat):.2f} s, min {min(lat):.2f}, max {max(lat):.2f}")
        print(f"  processingMs: avg {sum(pms)/len(pms):.0f}, max {max(pms)}")
        