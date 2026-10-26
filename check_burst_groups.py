import boto3

t = boto3.resource("dynamodb", region_name="ap-south-1").Table("SnapScaleImages")
items, kw = [], {}
while True:
    r = t.scan(**kw)
    items += r["Items"]
    if "LastEvaluatedKey" not in r:
        break
    kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

burst = [i for i in items if "burst" in (i.get("originalFilename") or "").lower()]
counts = {}
for i in burst:
    key = i["createdAt"][:16]
    counts[key] = counts.get(key, 0) + 1
for k in sorted(counts):
    print(k, counts[k])
print("total burst records:", len(burst))
