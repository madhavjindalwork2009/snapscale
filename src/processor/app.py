"""SnapScale processor Lambda: SQS -> Pillow -> S3 + DynamoDB."""
import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

from image_utils import ImageValidationError, process_image

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]
LEASE_SECONDS = 60


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            handle_message(record["body"])
        except Exception:
            logger.exception("Message failed: %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def handle_message(body):
    message = json.loads(body)
    if message.get("Event") == "s3:TestEvent":
        return
    for rec in message.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key = unquote_plus(rec["s3"]["object"]["key"])
        process_object(bucket, key, rec.get("eventTime"))


def claim(image_id, bucket, key, uploaded_at):
    """Take the job. False means it is already done or someone else has it."""
    now = int(time.time())
    try:
        table.update_item(
            Key={"imageId": image_id},
            UpdateExpression=(
                "SET #s = :processing, leaseExpiresAt = :lease, startedAt = :now, "
                "originalBucket = :b, originalKey = :k, "
                "uploadedAt = if_not_exists(uploadedAt, :up) ADD attempts :one"
            ),
            ConditionExpression=(
                "attribute_not_exists(imageId) OR #s IN (:pending, :retrying) "
                "OR (#s = :processing AND leaseExpiresAt < :now)"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":processing": "PROCESSING",
                ":pending": "PENDING",
                ":retrying": "RETRYING",
                ":lease": now + LEASE_SECONDS,
                ":now": now,
                ":b": bucket,
                ":k": key,
                ":up": uploaded_at,
                ":one": 1,
            },
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def mark_failed(image_id, message):
    table.update_item(
        Key={"imageId": image_id},
        UpdateExpression="SET #s = :s, errorMessage = :m, completedAt = :t REMOVE leaseExpiresAt",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "FAILED", ":m": message[:500], ":t": now_iso()},
    )


def mark_retrying(image_id, message):
    table.update_item(
        Key={"imageId": image_id},
        UpdateExpression="SET #s = :s, errorMessage = :m REMOVE leaseExpiresAt",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "RETRYING", ":m": message[:500]},
    )


def mark_completed(image_id, result, variants, processing_ms):
    table.update_item(
        Key={"imageId": image_id},
        UpdateExpression=(
            "SET #s = :s, completedAt = :t, processingMs = :ms, imageFormat = :f, "
            "originalWidth = :w, originalHeight = :h, originalSizeBytes = :sz, "
            "variants = :v REMOVE leaseExpiresAt, errorMessage"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "COMPLETED",
            ":t": now_iso(),
            ":ms": processing_ms,
            ":f": result["format"],
            ":w": result["original"]["width"],
            ":h": result["original"]["height"],
            ":sz": result["original"]["size_bytes"],
            ":v": variants,
        },
    )


def process_object(bucket, key, event_time):
    image_id = key.rsplit("/", 1)[-1]
    if not claim(image_id, bucket, key, event_time or now_iso()):
        logger.info("Skipping %s: already completed, failed or in progress", image_id)
        return

    started = time.time()
    try:
        data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        result = process_image(data)
        variants = {}
        for name, v in result["variants"].items():
            out_key = f"processed/{image_id}/{name}{v['extension']}"
            s3.put_object(
                Bucket=PROCESSED_BUCKET,
                Key=out_key,
                Body=v["data"],
                ContentType=v["content_type"],
                CacheControl="public, max-age=31536000, immutable",
            )
            variants[name] = {
                "key": out_key,
                "width": v["width"],
                "height": v["height"],
                "sizeBytes": v["size_bytes"],
                "contentType": v["content_type"],
            }
    except ImageValidationError as exc:
        logger.warning("Rejected %s: %s", image_id, exc)
        mark_failed(image_id, str(exc))
        return
    except Exception as exc:
        mark_retrying(image_id, str(exc))
        raise

    processing_ms = int((time.time() - started) * 1000)
    mark_completed(image_id, result, variants, processing_ms)
    logger.info(json.dumps({
        "event": "image_processed",
        "imageId": image_id,
        "processingMs": processing_ms,
        "originalBytes": result["original"]["size_bytes"],
        "variantBytes": {n: x["sizeBytes"] for n, x in variants.items()},
    }))