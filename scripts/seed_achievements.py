"""
Seed script to populate the achievements collection in MongoDB.
Run this script to initialize all achievements in the database.

Achievement points are balanced to work with the scoring system:
- Bronze: 5-20 pts (easy wins)
- Silver: 25-45 pts (mid-game milestones)
- Gold: 60-100 pts (significant effort)
- Platinum: 90-175 pts (mastery)
"""

import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import os

# Achievement definitions - 20 total, balanced point economy
ACHIEVEMENTS = [
    # === COLLECTION (5) - Total: 250 pts ===
    {
        "id": "first_seed",
        "name": "First Seed",
        "description": "Add your first plant to your garden",
        "icon": "🌱",
        "category": "collection",
        "tier": "bronze",
        "condition_type": "plant_count",
        "condition_value": 1,
        "points": 10,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "budding_collector",
        "name": "Budding Collector",
        "description": "Grow your collection to 5 plants",
        "icon": "🪴",
        "category": "collection",
        "tier": "bronze",
        "condition_type": "plant_count",
        "condition_value": 5,
        "points": 20,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "plant_parent",
        "name": "Plant Parent",
        "description": "Nurture a collection of 10 plants",
        "icon": "🌿",
        "category": "collection",
        "tier": "silver",
        "condition_type": "plant_count",
        "condition_value": 10,
        "points": 35,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "urban_jungle",
        "name": "Urban Jungle",
        "description": "Build an impressive collection of 25 plants",
        "icon": "🌳",
        "category": "collection",
        "tier": "gold",
        "condition_type": "plant_count",
        "condition_value": 25,
        "points": 75,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "forest_keeper",
        "name": "Forest Keeper",
        "description": "Achieve the ultimate collection of 50 plants",
        "icon": "🏞️",
        "category": "collection",
        "tier": "platinum",
        "condition_type": "plant_count",
        "condition_value": 50,
        "points": 110,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    
    # === WATERING (5) - Total: 225 pts ===
    {
        "id": "first_drop",
        "name": "First Drop",
        "description": "Water a plant for the first time",
        "icon": "💧",
        "category": "watering",
        "tier": "bronze",
        "condition_type": "total_waterings",
        "condition_value": 1,
        "points": 5,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "regular_waterer",
        "name": "Regular Waterer",
        "description": "Water your plants 50 times",
        "icon": "🌊",
        "category": "watering",
        "tier": "bronze",
        "condition_type": "total_waterings",
        "condition_value": 50,
        "points": 20,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "hydration_expert",
        "name": "Hydration Expert",
        "description": "Water your plants 200 times",
        "icon": "🐳",
        "category": "watering",
        "tier": "silver",
        "condition_type": "total_waterings",
        "condition_value": 200,
        "points": 40,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "week_streak",
        "name": "Week Streak",
        "description": "Maintain a 7-day watering streak",
        "icon": "🔥",
        "category": "watering",
        "tier": "silver",
        "condition_type": "max_streak",
        "condition_value": 7,
        "points": 35,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "monthly_devotion",
        "name": "Monthly Devotion",
        "description": "Incredible! 30-day watering streak",
        "icon": "🏅",
        "category": "watering",
        "tier": "platinum",
        "condition_type": "max_streak",
        "condition_value": 30,
        "points": 125,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    
    # === HEALTH (4) - Total: 195 pts ===
    {
        "id": "green_thumb",
        "name": "Green Thumb",
        "description": "Keep 3 plants healthy at the same time",
        "icon": "💚",
        "category": "health",
        "tier": "bronze",
        "condition_type": "healthy_plants",
        "condition_value": 3,
        "points": 15,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "plant_doctor",
        "name": "Plant Doctor",
        "description": "Revive a stressed or unhealthy plant back to health",
        "icon": "🌟",
        "category": "health",
        "tier": "silver",
        "condition_type": "plants_revived",
        "condition_value": 1,
        "points": 30,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "thriving_garden",
        "name": "Thriving Garden",
        "description": "Keep 10 plants healthy at the same time",
        "icon": "🌈",
        "category": "health",
        "tier": "gold",
        "condition_type": "healthy_plants",
        "condition_value": 10,
        "points": 60,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "perfect_balance",
        "name": "Perfect Balance",
        "description": "Keep all plants healthy for 7 consecutive days",
        "icon": "✨",
        "category": "health",
        "tier": "platinum",
        "condition_type": "all_healthy_days",
        "condition_value": 7,
        "points": 90,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    
    # === KNOWLEDGE (3) - Total: 130 pts ===
    {
        "id": "curious_gardener",
        "name": "Curious Gardener",
        "description": "Identify 5 different plant species",
        "icon": "🔍",
        "category": "knowledge",
        "tier": "bronze",
        "condition_type": "unique_species",
        "condition_value": 5,
        "points": 15,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "plant_scholar",
        "name": "Plant Scholar",
        "description": "Identify 15 different plant species",
        "icon": "📚",
        "category": "knowledge",
        "tier": "silver",
        "condition_type": "unique_species",
        "condition_value": 15,
        "points": 40,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "master_botanist",
        "name": "Master Botanist",
        "description": "Identify 30 different plant species",
        "icon": "🎓",
        "category": "knowledge",
        "tier": "gold",
        "condition_type": "unique_species",
        "condition_value": 30,
        "points": 75,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    
    # === LOYALTY (3) - Total: 100 pts ===
    {
        "id": "early_adopter",
        "name": "Early Adopter",
        "description": "Welcome to Vatika! You joined our plant care community",
        "icon": "🎉",
        "category": "loyalty",
        "tier": "bronze",
        "condition_type": "signup_complete",
        "condition_value": 1,
        "points": 5,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "one_week_in",
        "name": "One Week In",
        "description": "Stay active for 7 days",
        "icon": "📅",
        "category": "loyalty",
        "tier": "silver",
        "condition_type": "days_since_signup",
        "condition_value": 7,
        "points": 25,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
    {
        "id": "dedicated_gardener",
        "name": "Dedicated Gardener",
        "description": "A month of nurturing your garden",
        "icon": "🏆",
        "category": "loyalty",
        "tier": "gold",
        "condition_type": "days_since_signup",
        "condition_value": 30,
        "points": 70,
        "is_active": True,
        "created_at": datetime.utcnow(),
    },
]


async def seed_achievements():
    """Seed the achievements collection."""
    # Get MongoDB connection string - use 'mongo' as hostname when running in Docker
    mongo_url = "mongodb+srv://vatika:FXT5WM8QL2WsOp3D@vatika.zfdem2i.mongodb.net/?appName=vatika"
    db_name = "vatika"

    
    print(f"Connecting to MongoDB at {mongo_url}...")
    client = AsyncIOMotorClient(mongo_url)

    db = client[db_name]
    collection = db["achievements"]
    
    # Drop existing achievements to replace with new ones
    print("Dropping existing achievements...")
    await collection.drop()
    
    # Create unique index on id field
    await collection.create_index("id", unique=True)
    
    print(f"Seeding {len(ACHIEVEMENTS)} achievements...")
    
    for achievement in ACHIEVEMENTS:
        result = await collection.insert_one(achievement)
        print(f"  ✓ Created: {achievement['name']} ({achievement['tier']}, {achievement['points']} pts)")
    
    # Verify
    count = await collection.count_documents({})
    total_pts = sum(a["points"] for a in ACHIEVEMENTS)
    print(f"\n✅ Done! Total achievements: {count}")
    print(f"📊 Total possible achievement points: {total_pts}")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(seed_achievements())
