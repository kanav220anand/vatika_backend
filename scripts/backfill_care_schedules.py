#!/usr/bin/env python3
"""
Backfill missing per-plant care schedules.

Older plant documents may not have `care_schedule` populated. This script looks up
the plant type in `plant_knowledge`, converts the string-based frequencies into
numeric day intervals, and stores the normalized schedule on each plant.

Usage:
  python scripts/backfill_care_schedules.py
"""

import asyncio
import os
import sys

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings
from app.plants.care_utils import convert_care_schedule_to_stored


def get_client(uri: str) -> AsyncIOMotorClient:
    client_kwargs = {}
    if "mongodb+srv://" in uri or "ssl=true" in uri.lower():
        client_kwargs["tlsCAFile"] = certifi.where()
    return AsyncIOMotorClient(uri, **client_kwargs)


async def backfill():
    settings = get_settings()
    client = get_client(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]
    plants = db["plants"]
    knowledge = db["plant_knowledge"]

    query = {"$or": [{"care_schedule": None}, {"care_schedule": {"$exists": False}}]}
    cursor = plants.find(query, {"plant_id": 1})

    scanned = 0
    updated = 0
    skipped = 0

    async for plant in cursor:
        scanned += 1
        plant_type_id = plant.get("plant_id")
        if not plant_type_id:
            skipped += 1
            continue

        kb = await knowledge.find_one({"plant_id": plant_type_id}, {"care": 1})
        if not kb or not kb.get("care"):
            skipped += 1
            continue

        care_schedule = convert_care_schedule_to_stored(kb["care"])
        if not care_schedule:
            skipped += 1
            continue

        result = await plants.update_one(
            {"_id": plant["_id"]},
            {"$set": {"care_schedule": care_schedule}},
        )
        if result.modified_count:
            updated += 1
        else:
            skipped += 1

    print(f"Scanned: {scanned} | Updated: {updated} | Skipped: {skipped}")
    client.close()


if __name__ == "__main__":
    asyncio.run(backfill())

