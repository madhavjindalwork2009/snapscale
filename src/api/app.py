"""SnapScale API Lambda: upload URLs and image status/variant lookups."""
import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ["AWS_REGION"]
TABLE_NAME = os.environ["TABLE_NAME"]
ORIGINAL_BUCKET = os.environ["ORIGINAL_BUCKET"]
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
CDN_DOMAIN = os.environ.get("CDN_DOMAIN", "")

UPLOAD_URL_SECONDS = 300
DOWNLOAD_URL_SECONDS = 3600
ALLOWED_TYPES = {"image/jpeg", "image/png"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
PUBLIC_FIELDS = (
    "imageId", "status", "contentType", "originalFilename", "imageFormat",
    "createdAt", "uploadedAt", "completedAt", "processingMs",
    "originalWidth", "originalHeight", "originalSizeBytes", "errorMessage",
)

s3 = boto3.client(
    "s3",
    region_name=REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
table = boto3.resource("dynamodb").Table(TABLE_NAME)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body, default=_json_default),
    }


def handler(event, context):
    try:
        method = event["httpMethod"]
        resource = event["resource"]
        if method == "POST" and resource == "/uploads":
            return create_upload(event)
        if method == "GET" and resource == "/images":
            return list_images(event)
        if method == "GET" and resource == "/images/{imageId}":
            return get_image(event)
        if method == "GET" and resource == "/images/{imageId}/variants":
            return get_variants(event)
        return response(404, {"error": "Route not found"})
    except ApiError as exc:
        return response(exc.status, {"error": exc.message})
    except Exception:
        logger.exception("Unhandled error")
        return response(500, {"error": "Internal server error"})


def parse_body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw)
    except ValueError:
        raise ApiError(400, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "Request body must be a JSON object")
    return body


def create_upload(event):
    body = parse_body(event)

    content_type = body.get("contentType")
    if content_type not in ALLOWED_TYPES:
        raise ApiError(400, "contentType must be image/jpeg or image/png")

    file_name = body.get("fileName")
    if file_name is not None:
        if not isinstance(file_name, str) or not file_name.strip() or len(file_name) > 255:
            raise ApiError(400, "fileName must be a string of 1 to 255 characters")
        file_name = file_name.strip()

    size = body.get("sizeBytes")
    if size is not None:
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_UPLOAD_BYTES:
            raise ApiError(400, f"sizeBytes must be an integer between 1 and {MAX_UPLOAD_BYTES}")

    image_id = str(uuid.uuid4())
    key = f"uploads/{image_id}"

    item = {
        "imageId": image_id,
        "status": "PENDING",
        "contentType": content_type,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if file_name:
        item["originalFilename"] = file_name
    if size is not None:
        item["declaredSizeBytes"] = size
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(imageId)")

    post = s3.generate_presigned_post(
        Bucket=ORIGINAL_BUCKET,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, MAX_UPLOAD_BYTES],
        ],
        ExpiresIn=UPLOAD_URL_SECONDS,
    )
    logger.info(json.dumps({"event": "upload_created", "imageId": image_id}))
    return response(201, {
        "imageId": image_id,
        "upload": post,
        "expiresInSeconds": UPLOAD_URL_SECONDS,
        "maxBytes": MAX_UPLOAD_BYTES,
    })


def public_item(item):
    out = {k: item[k] for k in PUBLIC_FIELDS if k in item}
    if "variants" in item:
        out["variants"] = {
            name: {k: v[k] for k in ("width", "height", "sizeBytes", "contentType") if k in v}
            for name, v in item["variants"].items()
        }
    return out


def load_item(event):
    image_id = (event.get("pathParameters") or {}).get("imageId", "")
    if not ID_PATTERN.match(image_id):
        raise ApiError(400, "Invalid imageId")
    item = table.get_item(Key={"imageId": image_id}).get("Item")
    if not item:
        raise ApiError(404, "Image not found")
    return item


def get_image(event):
    return response(200, public_item(load_item(event)))


def encode_token(key):
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def decode_token(token):
    try:
        key = json.loads(base64.urlsafe_b64decode(token.encode()))
        if not isinstance(key, dict) or set(key) != {"imageId"} or not ID_PATTERN.match(str(key["imageId"])):
            raise ValueError
        return key
    except Exception:
        raise ApiError(400, "Invalid nextToken")


def list_images(event):
    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", 20))
    except ValueError:
        raise ApiError(400, "limit must be an integer")
    if not 1 <= limit <= 50:
        raise ApiError(400, "limit must be between 1 and 50")

    kwargs = {"Limit": limit}
    if params.get("nextToken"):
        kwargs["ExclusiveStartKey"] = decode_token(params["nextToken"])

    result = table.scan(**kwargs)
    images = [public_item(i) for i in result.get("Items", [])]
    images.sort(key=lambda i: i.get("createdAt") or i.get("uploadedAt") or "", reverse=True)

    body = {"images": images, "count": len(images)}
    if "LastEvaluatedKey" in result:
        body["nextToken"] = encode_token(result["LastEvaluatedKey"])
    return response(200, body)


def get_variants(event):
    item = load_item(event)
    if item.get("status") != "COMPLETED":
        return response(409, {
            "error": "Image is not ready",
            "imageId": item["imageId"],
            "status": item.get("status"),
        })

    variants = {}
    for name, v in item["variants"].items():
        if CDN_DOMAIN:
            url = f"https://{CDN_DOMAIN}/{v['key']}"
        else:
            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": PROCESSED_BUCKET, "Key": v["key"]},
                ExpiresIn=DOWNLOAD_URL_SECONDS,
            )
        variants[name] = {
            "url": url,
            "width": v["width"],
            "height": v["height"],
            "sizeBytes": v["sizeBytes"],
            "contentType": v["contentType"],
        }
    body = {"imageId": item["imageId"], "variants": variants}
    if not CDN_DOMAIN:
        body["urlExpiresInSeconds"] = DOWNLOAD_URL_SECONDS
    return response(200, body)