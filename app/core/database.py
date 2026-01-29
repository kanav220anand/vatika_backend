"""
MongoDB database connection and utilities.
"""

from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import certifi
from urllib.parse import urlparse
from app.core.config import get_settings

settings = get_settings()


class Database:
    """MongoDB database connection manager."""
    
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None
    
    @classmethod
    async def connect(cls):
        """Connect to MongoDB."""
        mongo_uri = (getattr(settings, "MONGODB_URI", "") or "").strip() or (settings.MONGO_URI or "").strip()
        parsed = urlparse(mongo_uri)
        path = (parsed.path or "").lstrip("/")
        db_name = path.split("/")[0] if path else settings.MONGO_DB_NAME

        # Use certifi for SSL certificates to avoid handshake errors on some systems (especially macOS)
        # Configure SSL context for external databases (like Atlas)
        client_kwargs = {}
        if "mongodb+srv://" in mongo_uri or "ssl=true" in mongo_uri.lower():
            client_kwargs["tlsCAFile"] = certifi.where()

        cls.client = AsyncIOMotorClient(
            mongo_uri,
            **client_kwargs
        )
        cls.db = cls.client[db_name]
        
        # Create indexes
        await cls._create_indexes()
        await cls._ensure_internal_master_docs()
        
        print(f"Connected to MongoDB: {db_name}")
    
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
        # ANALYSIS-002: one initial snapshot per plant (code guard exists; this index enforces it when supported).
        try:
            await cls.db.health_snapshots.create_index(
                [("plant_id", 1), ("snapshot_type", 1)],
                unique=True,
                partialFilterExpression={"snapshot_type": "initial"},
            )
        except Exception:
            pass

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
        # Backfill cleanup: if any old docs accidentally stored dedupe_key: null, remove it so sparse unique index works.
        # First, try to drop the existing index if it exists (in case it has issues)
        try:
            await cls.db.notifications.drop_index("user_id_1_dedupe_key_1")
        except Exception:
            pass  # Index doesn't exist or already dropped
        
        # Clean up duplicate notifications with null dedupe_key BEFORE creating index
        try:
            # Find all documents with null dedupe_key, group by user_id, keep only the oldest one per user
            pipeline = [
                {"$match": {"dedupe_key": None}},
                {"$sort": {"created_at": 1}},
                {"$group": {
                    "_id": "$user_id",
                    "ids": {"$push": "$_id"},
                    "count": {"$sum": 1}
                }},
                {"$match": {"count": {"$gt": 1}}}
            ]
            duplicates_found = False
            async for dup in cls.db.notifications.aggregate(pipeline):
                duplicates_found = True
                # Keep the first (oldest) document, delete the rest
                ids_to_delete = dup["ids"][1:]
                if ids_to_delete:
                    result = await cls.db.notifications.delete_many({"_id": {"$in": ids_to_delete}})
                    print(f"Cleaned up {result.deleted_count} duplicate notifications for user {dup['_id']}")
            
            # Remove dedupe_key field from all documents that have null or empty string
            result = await cls.db.notifications.update_many(
                {"dedupe_key": {"$in": [None, ""]}}, 
                {"$unset": {"dedupe_key": ""}}
            )
            if result.modified_count > 0:
                print(f"Removed dedupe_key field from {result.modified_count} notifications")
        except Exception as e:
            print(f"Warning: Could not clean up dedupe_key fields: {e}")
        
        # Watering reminders/checks: idempotency per user per plant per day.
        # Sparse to avoid old docs (without dedupe_key) colliding under a unique index.
        try:
            await cls.db.notifications.create_index([("user_id", 1), ("dedupe_key", 1)], unique=True, sparse=True)
        except Exception as e:
            print(f"Warning: Could not create notifications dedupe index: {e}")
            # Continue anyway - the app can work without this index, but deduplication won't work

        # Push notifications (SNS device registration + preferences + send queue)
        await cls.db.push_devices.create_index("app_install_id", unique=True)
        await cls.db.push_devices.create_index([("user_id", 1), ("status", 1)])
        await cls.db.push_devices.create_index("token")

        await cls.db.push_preferences.create_index("user_id", unique=True)

        await cls.db.push_notifications.create_index([("status", 1), ("delivery_time", 1)])
        await cls.db.push_notifications.create_index("user_id")

        await cls.db.push_log.create_index([("user_id", 1), ("created_at", -1)])
        await cls.db.push_log.create_index([("device_id", 1), ("created_at", -1)])

        # AI usage / rate limits (COST-001)
        await cls.db.rate_limits.create_index([("expires_at", 1)], expireAfterSeconds=0)
        await cls.db.rate_limits.create_index([("key", 1), ("window_start", 1)])
        await cls.db.ai_usage.create_index([("user_id", 1), ("created_at", -1)])
        await cls.db.ai_usage.create_index([("endpoint", 1), ("created_at", -1)])

        # Jobs (JOBS-001)
        await cls.db.jobs.create_index("job_id", unique=True)
        await cls.db.jobs.create_index([("user_id", 1), ("created_at", -1)])
        await cls.db.jobs.create_index([("status", 1), ("created_at", -1)])
        await cls.db.jobs.create_index([("user_id", 1), ("type", 1), ("idempotency_key", 1), ("created_at", -1)])
        retention_days = int(getattr(settings, "JOBS_RETENTION_DAYS", 0) or 0)
        if retention_days > 0:
            await cls.db.jobs.create_index(
                [("created_at", 1)],
                expireAfterSeconds=retention_days * 24 * 60 * 60,
            )

        # Internal master data
        # `_id` is already uniquely indexed by Mongo; keep this non-unique for compatibility.
        await cls.db.internal_master.create_index("_id")

        # Care Club collections
        await cls.db.care_club_posts.create_index([("created_at", -1)])
        await cls.db.care_club_posts.create_index([("author_id", 1)])
        await cls.db.care_club_posts.create_index([("plant_id", 1)])
        await cls.db.care_club_posts.create_index([("status", 1), ("created_at", -1)])
        await cls.db.care_club_posts.create_index([("last_activity_at", -1)])
        await cls.db.care_club_posts.create_index([("moderation_status", 1), ("created_at", -1)])

        await cls.db.care_club_comments.create_index([("post_id", 1), ("created_at", 1)])
        await cls.db.care_club_comments.create_index([("post_id", 1), ("moderation_status", 1), ("created_at", 1)])
        await cls.db.care_club_comments.create_index([("author_id", 1)])

        await cls.db.care_club_helpful_votes.create_index([("comment_id", 1), ("user_id", 1)], unique=True)
        await cls.db.care_club_helpful_votes.create_index([("post_id", 1)])
        await cls.db.care_club_helpful_votes.create_index([("user_id", 1), ("created_at", -1)])

        # Moderation collections
        await cls.db.care_club_reports.create_index([("status", 1), ("created_at", -1)])
        await cls.db.care_club_reports.create_index([("target_type", 1), ("target_id", 1)])
        await cls.db.care_club_reports.create_index(
            [("reporter_user_id", 1), ("target_type", 1), ("target_id", 1)],
            unique=True,
        )
        await cls.db.moderation_actions.create_index([("created_at", -1)])
        await cls.db.moderation_actions.create_index([("target_type", 1), ("target_id", 1), ("created_at", -1)])

        # Weather forecast cache collection
        await cls.db.weather_forecast_cache.create_index("city_key", unique=True)
        await cls.db.weather_forecast_cache.create_index([("fetched_at", -1)])

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
