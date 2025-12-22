"""
Seed script for user_levels collection.
Run: python -m scripts.seed_levels
"""

import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

# Use MONGO_URI to match docker-compose environment
MONGO_URL = os.getenv("MONGO_URI", os.getenv("MONGO_URL", "mongodb://mongo:27017"))
DB_NAME = os.getenv("MONGO_DB_NAME", "plantsitter")

LEVELS_DATA = [
    {
        "level": 1,
        "title": "Seed",
        "icon": "🫘",
        "min_points": 0,
        "max_points": 99,
        "description": "Just planted, full of potential",
        "color": "#8B5A2B",
        "badge_image_url": None,
        "perks": ["access_basic_tips"],
        "sort_order": 1,
        "is_active": True,
    },
    {
        "level": 2,
        "title": "Sprout",
        "icon": "🌱",
        "min_points": 100,
        "max_points": 299,
        "description": "Breaking through the soil",
        "color": "#90EE90",
        "badge_image_url": None,
        "perks": ["access_basic_tips", "watering_reminders"],
        "sort_order": 2,
        "is_active": True,
    },
    {
        "level": 3,
        "title": "Seedling",
        "icon": "🌿",
        "min_points": 300,
        "max_points": 799,
        "description": "Growing stronger every day",
        "color": "#32CD32",
        "badge_image_url": None,
        "perks": ["access_basic_tips", "watering_reminders", "plant_identification"],
        "sort_order": 3,
        "is_active": True,
    },
    {
        "level": 4,
        "title": "Sapling",
        "icon": "🪴",
        "min_points": 800,
        "max_points": 1999,
        "description": "Establishing deep roots",
        "color": "#228B22",
        "badge_image_url": None,
        "perks": ["access_basic_tips", "watering_reminders", "plant_identification", "care_analytics"],
        "sort_order": 4,
        "is_active": True,
    },
    {
        "level": 5,
        "title": "Blossom",
        "icon": "🌸",
        "min_points": 2000,
        "max_points": 4999,
        "description": "In full bloom",
        "color": "#FFB6C1",
        "badge_image_url": None,
        "perks": ["access_basic_tips", "watering_reminders", "plant_identification", "care_analytics", "expert_tips"],
        "sort_order": 5,
        "is_active": True,
    },
    {
        "level": 6,
        "title": "Evergreen",
        "icon": "🌳",
        "min_points": 5000,
        "max_points": None,
        "description": "A timeless gardener",
        "color": "#006400",
        "badge_image_url": None,
        "perks": ["access_basic_tips", "watering_reminders", "plant_identification", "care_analytics", "expert_tips", "beta_features"],
        "sort_order": 6,
        "is_active": True,
    },
]


async def seed_levels():
    """Seed the user_levels collection."""
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    collection = db["user_levels"]
    
    print(f"Connected to MongoDB: {MONGO_URL}/{DB_NAME}")
    
    # Check if levels already exist
    existing_count = await collection.count_documents({})
    if existing_count > 0:
        print(f"Found {existing_count} existing levels. Dropping and re-seeding...")
        await collection.drop()
    
    # Add timestamps
    now = datetime.utcnow()
    for level in LEVELS_DATA:
        level["created_at"] = now
        level["updated_at"] = now
    
    # Insert all levels
    result = await collection.insert_many(LEVELS_DATA)
    print(f"Inserted {len(result.inserted_ids)} levels")
    
    # Create indexes
    await collection.create_index("level", unique=True)
    await collection.create_index("min_points")
    await collection.create_index([("is_active", 1), ("sort_order", 1)])
    print("Created indexes")
    
    # Verify
    levels = await collection.find({}).to_list(length=100)
    print("\nSeeded levels:")
    for level in levels:
        max_pts = level['max_points'] if level['max_points'] else "∞"
        print(f"  {level['icon']} Level {level['level']}: {level['title']} ({level['min_points']}-{max_pts} pts)")
    
    client.close()
    print("\n✅ Seed complete!")


if __name__ == "__main__":
    asyncio.run(seed_levels())
