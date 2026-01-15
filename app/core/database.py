"""
MongoDB database connection and utilities.
"""

from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import certifi
from app.core.config import get_settings

settings = get_settings()


class Database:
    """MongoDB database connection manager."""
    
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None
    
    @classmethod
    async def connect(cls):
        """Connect to MongoDB."""
        # Use certifi for SSL certificates to avoid handshake errors on some systems (especially macOS)
        # Configure SSL context for external databases (like Atlas)
        client_kwargs = {}
        if "mongodb+srv://" in settings.MONGO_URI or "ssl=true" in settings.MONGO_URI.lower():
            client_kwargs["tlsCAFile"] = certifi.where()

        cls.client = AsyncIOMotorClient(
            settings.MONGO_URI,
            **client_kwargs
        )
        cls.db = cls.client[settings.MONGO_DB_NAME]
        
        # Create indexes
        await cls._create_indexes()
        await cls._ensure_internal_master_docs()
        
        print(f"Connected to MongoDB: {settings.MONGO_DB_NAME}")
    
    @classmethod
    async def disconnect(cls):
        """Disconnect from MongoDB."""
        if cls.client:
            cls.client.close()
            print("Disconnected from MongoDB")
    
    @classmethod
    async def _create_indexes(cls):
        """Create database indexes for better query performance."""
        # Users collection
        await cls.db.users.create_index("email", unique=True)
        
        # Plants collection
        await cls.db.plants.create_index("user_id")
        await cls.db.plants.create_index("plant_id")
        
        # Plant knowledge base collection
        await cls.db.plant_knowledge.create_index("plant_id", unique=True)
        await cls.db.plant_knowledge.create_index("common_names")

        # Health snapshots collection (timeline)
        await cls.db.health_snapshots.create_index([("user_id", 1), ("plant_id", 1), ("created_at", -1)])

        # Events collection (history/timeline)
        await cls.db.events.create_index([("user_id", 1), ("plant_id", 1), ("created_at", -1)])
        await cls.db.events.create_index([("user_id", 1), ("event_type", 1), ("created_at", -1)])

        # Cities collection
        await cls.db.cities.create_index("name_lower", unique=True)
        await cls.db.cities.create_index("state_lower")
        await cls.db.cities.create_index("rank")

        # Articles collection
        await cls.db.articles.create_index([("is_active", 1), ("scope", 1), ("priority", -1)])
        await cls.db.articles.create_index([("issue_tags", 1), ("is_active", 1)])
        await cls.db.articles.create_index([("plant_family", 1), ("is_active", 1)])

        # Notifications collection (supports cheap unread-count + list ordering)
        await cls.db.notifications.create_index([("user_id", 1), ("is_read", 1), ("created_at", -1)])
        await cls.db.notifications.create_index([("user_id", 1), ("created_at", -1)])

        # Internal master data
        # `_id` is already uniquely indexed by Mongo; keep this non-unique for compatibility.
        await cls.db.internal_master.create_index("_id")

        # Care Club collections
        await cls.db.care_club_posts.create_index([("created_at", -1)])
        await cls.db.care_club_posts.create_index([("author_id", 1)])
        await cls.db.care_club_posts.create_index([("plant_id", 1)])
        await cls.db.care_club_posts.create_index([("status", 1), ("created_at", -1)])
        await cls.db.care_club_posts.create_index([("last_activity_at", -1)])

        await cls.db.care_club_comments.create_index([("post_id", 1), ("created_at", 1)])
        await cls.db.care_club_comments.create_index([("author_id", 1)])

        await cls.db.care_club_helpful_votes.create_index([("comment_id", 1), ("user_id", 1)], unique=True)
        await cls.db.care_club_helpful_votes.create_index([("post_id", 1)])

    @classmethod
    async def _ensure_internal_master_docs(cls):
        """Seed/ensure internal master data documents exist."""
        issue_tags_doc = {
            "_id": "issue_tags",
            "primary_issue_tags": [
                # 🌱 Water & Roots
                "overwatering",
                "underwatering",
                "root_rot",
                "root_stress",
                "poor_drainage",
                "dry_soil",
                "water_imbalance",
                # ☀️ Light
                "low_light",
                "light_excess",
                "direct_sunlight",
                "sun_stress",
                "light_instability",
                # 🌿 Leaves & Growth Symptoms
                "yellow_leaves",
                "leaf_drooping",
                "leaf_curling",
                "leaf_spots",
                "leaf_shedding",
                "leaf_softness",
                "leaf_crisping",
                "leaf_wrinkling",
                # 🌡 Environment & Stress
                "heat_stress",
                "cold_stress",
                "low_humidity",
                "high_humidity",
                "airflow_issues",
                "environmental_change",
                "relocation_stress",
                "air_pollution",
                # 🌸 Flowering-specific
                "bud_drop",
                "early_flower_drop",
                "no_blooming",
                "flowering_cycle_disruption",
                # 🌿 Herbs & Edibles
                "leggy_growth",
                "bolting",
                "loss_of_flavor",
                "slow_edible_growth",
                # 🌴 Trees, Woody & Ferns
                "slow_growth",
                "establishment_stress",
                "fragile_recovery",
            ],
            "plant_families": [
                "succulent_dry",
                "tropical_foliage",
                "flowering",
                "herbs_edibles",
                "woody_trees",
                "ferns_moisture",
            ],
            "health_severity": ["low", "medium", "high"],
            "confidence_buckets": ["high", "medium", "low"],
            "step4_allowed_tags": {
                "light": [
                    "low_light",
                    "light_excess",
                    "direct_sunlight",
                    "sun_stress",
                    "light_instability",
                ],
                "growth": [
                    "slow_growth",
                    "recovery_time",
                    "new_growth",
                    "stalled_growth",
                ],
                "environment": [
                    "low_humidity",
                    "high_humidity",
                    "heat_stress",
                    "airflow_issues",
                    "environmental_change",
                ],
            },
            "updated_at": datetime.utcnow(),
        }

        await cls.db.internal_master.update_one(
            {"_id": "issue_tags"},
            {"$set": issue_tags_doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
    
    @classmethod
    def get_collection(cls, name: str):
        """Get a collection by name."""
        return cls.db[name]


def get_db() -> AsyncIOMotorDatabase:
    """Get the database instance."""
    return Database.db
