import json
import sys

import boto3

table = boto3.resource("dynamodb", region_name="ap-south-1").Table("SnapScaleImages")
item = table.get_item(Key={"imageId": sys.argv[1]}).get("Item")
print(json.dumps(item, indent=2, default=str) if item else "Not found yet")