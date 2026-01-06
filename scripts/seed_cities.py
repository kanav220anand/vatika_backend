#!/usr/bin/env python3
"""
Seed script for cities collection.

Uses the local cities_r2.csv (top ~500 Indian cities) and stores only the
fields needed for search/typeahead: name, state, latitude, longitude.
Duplicates by city name are dropped (keeps the first occurrence).
"""

import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

# Make app package importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings


def get_client(uri: str) -> AsyncIOMotorClient:
    """Create Mongo client with TLS if needed."""
    client_kwargs = {}
    if "mongodb+srv://" in uri or "ssl=true" in uri.lower():
        client_kwargs["tlsCAFile"] = certifi.where()
    return AsyncIOMotorClient(uri, **client_kwargs)


async def seed_cities():
    settings = get_settings()
    client = get_client(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]
    collection = db["cities"]

    csv_path = Path(__file__).resolve().parent.parent / "cities_r2.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found at {csv_path}")

    docs = []
    seen = set()
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            name = row["name_of_city"].strip()
            state = row["state_name"].strip()
            key = name.lower()
            if key in seen:
                # Keep only one Aurangabad (or any duplicate city name)
                continue
            seen.add(key)

            lat = lng = None
            loc = (row.get("location") or "").strip().strip('"')
            if loc and "," in loc:
                lat_str, lng_str = [p.strip() for p in loc.split(",", 1)]
                try:
                    lat = float(lat_str)
                    lng = float(lng_str)
                except ValueError:
                    lat = lng = None

            docs.append(
                {
                    "name": name,
                    "state": state,
                    "lat": lat,
                    "lng": lng,
                    "name_lower": name.lower(),
                    "state_lower": state.lower(),
                    "rank": idx,  # preserve source ordering for sort
                }
            )

    # Replace existing data
    await collection.delete_many({})
    if docs:
        await collection.insert_many(docs)
        await collection.create_index("name_lower", unique=True)
        await collection.create_index("state_lower")
        await collection.create_index("rank")
    print(f"Seeded {len(docs)} cities")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed_cities())
