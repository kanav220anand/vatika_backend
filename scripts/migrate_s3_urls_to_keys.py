#!/usr/bin/env python3
"""
Migrate older Mongo records that stored full S3 URLs (including presigned URLs)
back into canonical S3 object keys.

Why:
- Presigned URLs expire; storing them breaks image loading.
- The backend should store only keys and generate fresh presigned GET URLs at runtime.

Collections updated (best-effort):
- plants.image_url
- health_snapshots.image_key, health_snapshots.thumbnail_key
- users.profile_picture (only if it points to our S3 bucket)
- care_club_posts.photo_urls (array)
- care_club_comments.photo_urls (array)

Usage:
  python scripts/migrate_s3_urls_to_keys.py --dry-run
  python scripts/migrate_s3_urls_to_keys.py
"""

import argparse
import asyncio
import os
import sys
from typing import Optional

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings
from app.core.s3_keys import normalize_s3_key


def get_client(uri: str) -> AsyncIOMotorClient:
    client_kwargs = {}
    if "mongodb+srv://" in uri or "ssl=true" in uri.lower():
        client_kwargs["tlsCAFile"] = certifi.where()
    return AsyncIOMotorClient(uri, **client_kwargs)


def normalize(value: Optional[str], *, bucket: str, region: str) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    return normalize_s3_key(value, bucket=bucket, region=region)


async def migrate(dry_run: bool) -> None:
    settings = get_settings()
    client = get_client(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]

    bucket = settings.AWS_S3_BUCKET
    region = settings.AWS_REGION

    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET must be set for this migration.")

    changed = {
        "plants": 0,
        "health_snapshots": 0,
        "users": 0,
        "care_club_posts": 0,
        "care_club_comments": 0,
    }
    scanned = {
        "plants": 0,
        "health_snapshots": 0,
        "users": 0,
        "care_club_posts": 0,
        "care_club_comments": 0,
    }

    # ---------------- plants.image_url ----------------
    plants = db["plants"]
    cursor = plants.find({"image_url": {"$type": "string"}}, {"image_url": 1})
    async for doc in cursor:
        scanned["plants"] += 1
        cur = doc.get("image_url")
        key = normalize(cur, bucket=bucket, region=region)
        if not key:
            continue
        if key == cur:
            # Already a key; skip.
            continue
        if dry_run:
            changed["plants"] += 1
            continue
        res = await plants.update_one({"_id": doc["_id"]}, {"$set": {"image_url": key}})
        if res.modified_count:
            changed["plants"] += 1

    # -------- health_snapshots.image_key/thumbnail_key --------
    snaps = db["health_snapshots"]
    cursor = snaps.find(
        {
            "$or": [
                {"image_key": {"$type": "string"}},
                {"thumbnail_key": {"$type": "string"}},
            ]
        },
        {"image_key": 1, "thumbnail_key": 1},
    )
    async for doc in cursor:
        scanned["health_snapshots"] += 1
        updates = {}

        for field in ("image_key", "thumbnail_key"):
            cur = doc.get(field)
            if not isinstance(cur, str) or not cur:
                continue
            key = normalize(cur, bucket=bucket, region=region)
            if key and key != cur:
                updates[field] = key

        if not updates:
            continue

        if dry_run:
            changed["health_snapshots"] += 1
            continue

        res = await snaps.update_one({"_id": doc["_id"]}, {"$set": updates})
        if res.modified_count:
            changed["health_snapshots"] += 1

    # ---------------- users.profile_picture ----------------
    users = db["users"]
    cursor = users.find({"profile_picture": {"$type": "string"}}, {"profile_picture": 1})
    async for doc in cursor:
        scanned["users"] += 1
        cur = doc.get("profile_picture")
        key = normalize(cur, bucket=bucket, region=region)
        if not key:
            continue
        if key == cur:
            continue
        if dry_run:
            changed["users"] += 1
            continue
        res = await users.update_one({"_id": doc["_id"]}, {"$set": {"profile_picture": key}})
        if res.modified_count:
            changed["users"] += 1

    # ---------------- care_club_posts.photo_urls ----------------
    posts = db["care_club_posts"]
    cursor = posts.find({"photo_urls": {"$type": "array"}}, {"photo_urls": 1})
    async for doc in cursor:
        scanned["care_club_posts"] += 1
        cur_list = doc.get("photo_urls") or []
        if not isinstance(cur_list, list) or not cur_list:
            continue

        updated = []
        did_change = False
        for item in cur_list:
            if not isinstance(item, str):
                updated.append(item)
                continue
            key = normalize(item, bucket=bucket, region=region)
            if key and key != item:
                updated.append(key)
                did_change = True
            else:
                updated.append(item)

        if not did_change:
            continue
        if dry_run:
            changed["care_club_posts"] += 1
            continue
        res = await posts.update_one({"_id": doc["_id"]}, {"$set": {"photo_urls": updated}})
        if res.modified_count:
            changed["care_club_posts"] += 1

    # ---------------- care_club_comments.photo_urls ----------------
    comments = db["care_club_comments"]
    cursor = comments.find({"photo_urls": {"$type": "array"}}, {"photo_urls": 1})
    async for doc in cursor:
        scanned["care_club_comments"] += 1
        cur_list = doc.get("photo_urls") or []
        if not isinstance(cur_list, list) or not cur_list:
            continue

        updated = []
        did_change = False
        for item in cur_list:
            if not isinstance(item, str):
                updated.append(item)
                continue
            key = normalize(item, bucket=bucket, region=region)
            if key and key != item:
                updated.append(key)
                did_change = True
            else:
                updated.append(item)

        if not did_change:
            continue
        if dry_run:
            changed["care_club_comments"] += 1
            continue
        res = await comments.update_one({"_id": doc["_id"]}, {"$set": {"photo_urls": updated}})
        if res.modified_count:
            changed["care_club_comments"] += 1

    print("Scanned:", scanned)
    print("Would change:" if dry_run else "Changed:", changed)
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Count changes without updating Mongo")
    args = parser.parse_args()
    asyncio.run(migrate(args.dry_run))


if __name__ == "__main__":
    main()
