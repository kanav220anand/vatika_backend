#!/usr/bin/env python3
"""
Seed script for recommended plants.
Run this script to populate the database with beginner-friendly plants.

Usage: python scripts/seed_recommended_plants.py
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Database


# Recommended plants data
RECOMMENDED_PLANTS = [
    {
        "plant_id": "money_plant",
        "common_name": "Money Plant",
        "scientific_name": "Epipremnum aureum",
        "image_url": "https://images.unsplash.com/photo-1637967886160-fd78dc3ce3f5?w=400",
        "difficulty": "easy",
        "light_needs": "low",
        "water_frequency": "Every 4-5 days",
        "description": "Air-purifying vine that thrives in low light. Perfect for beginners and brings good luck!",
        "is_beginner_friendly": True,
        "order": 1,
    },
    {
        "plant_id": "snake_plant",
        "common_name": "Snake Plant",
        "scientific_name": "Sansevieria trifasciata",
        "image_url": "https://images.unsplash.com/photo-1593482892290-f54927ae1bb6?w=400",
        "difficulty": "easy",
        "light_needs": "low",
        "water_frequency": "Every 2-3 weeks",
        "description": "Nearly indestructible! Tolerates neglect and purifies air even at night.",
        "is_beginner_friendly": True,
        "order": 2,
    },
    {
        "plant_id": "pothos",
        "common_name": "Pothos",
        "scientific_name": "Epipremnum aureum",
        "image_url": "https://images.unsplash.com/photo-1600411833196-7c1f6b1a8b90?w=400",
        "difficulty": "easy",
        "light_needs": "medium",
        "water_frequency": "Every 5-7 days",
        "description": "Beautiful trailing vine that grows fast. Great for shelves and hanging baskets.",
        "is_beginner_friendly": True,
        "order": 3,
    },
    {
        "plant_id": "spider_plant",
        "common_name": "Spider Plant",
        "scientific_name": "Chlorophytum comosum",
        "image_url": "https://images.unsplash.com/photo-1572688484438-313a6e50c333?w=400",
        "difficulty": "easy",
        "light_needs": "medium",
        "water_frequency": "Every 5-7 days",
        "description": "Produces baby plants you can share with friends. Excellent air purifier.",
        "is_beginner_friendly": True,
        "order": 4,
    },
    {
        "plant_id": "peace_lily",
        "common_name": "Peace Lily",
        "scientific_name": "Spathiphyllum",
        "image_url": "https://images.unsplash.com/photo-1616690002178-4f1c26d23734?w=400",
        "difficulty": "medium",
        "light_needs": "low",
        "water_frequency": "Every 5-7 days",
        "description": "Elegant white flowers that bloom in low light. Tells you when it's thirsty by drooping.",
        "is_beginner_friendly": True,
        "order": 5,
    },
    {
        "plant_id": "jade_plant",
        "common_name": "Jade Plant",
        "scientific_name": "Crassula ovata",
        "image_url": "https://images.unsplash.com/photo-1509423350716-97f9360b4e09?w=400",
        "difficulty": "easy",
        "light_needs": "bright",
        "water_frequency": "Every 2-3 weeks",
        "description": "Succulent that symbolizes prosperity. Stores water in its thick leaves.",
        "is_beginner_friendly": True,
        "order": 6,
    },
    {
        "plant_id": "aloe_vera",
        "common_name": "Aloe Vera",
        "scientific_name": "Aloe barbadensis miller",
        "image_url": "https://images.unsplash.com/photo-1596547609652-9cf5d8c76921?w=400",
        "difficulty": "easy",
        "light_needs": "bright",
        "water_frequency": "Every 2-3 weeks",
        "description": "Medicinal gel for burns and skin. Hardy succulent that loves sunshine.",
        "is_beginner_friendly": True,
        "order": 7,
    },
    {
        "plant_id": "rubber_plant",
        "common_name": "Rubber Plant",
        "scientific_name": "Ficus elastica",
        "image_url": "https://images.unsplash.com/photo-1545241047-6083a3684587?w=400",
        "difficulty": "medium",
        "light_needs": "medium",
        "water_frequency": "Every 7-10 days",
        "description": "Bold, glossy leaves that make a statement. Great for corners and empty spaces.",
        "is_beginner_friendly": True,
        "order": 8,
    },
]


async def seed_recommended_plants():
    """Seed the database with recommended plants."""
    print("🌱 Connecting to database...")
    await Database.connect()
    
    collection = Database.get_collection("recommended_plants")
    
    # Check if plants already exist
    existing_count = await collection.count_documents({})
    if existing_count > 0:
        print(f"⚠️  Found {existing_count} existing plants. Clearing collection...")
        await collection.delete_many({})
    
    # Insert plants
    print(f"📝 Inserting {len(RECOMMENDED_PLANTS)} recommended plants...")
    result = await collection.insert_many(RECOMMENDED_PLANTS)
    
    print(f"✅ Successfully seeded {len(result.inserted_ids)} plants!")
    
    # Create index on plant_id
    await collection.create_index("plant_id", unique=True)
    await collection.create_index("order")
    print("📊 Created indexes on plant_id and order")
    
    await Database.disconnect()
    print("🎉 Done!")


if __name__ == "__main__":
    asyncio.run(seed_recommended_plants())
