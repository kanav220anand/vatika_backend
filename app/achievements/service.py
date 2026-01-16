"""Achievement service for checking and unlocking achievements."""

from datetime import datetime
from typing import List, Dict, Tuple, Optional
from bson import ObjectId

from app.core.database import Database
from app.achievements.models import (
    AchievementResponse,
    AchievementsListResponse,
    UserStats,
)

WATERING_EVENT_TYPES = ("watered", "plant_watered")


class AchievementService:
    """Service for managing user achievements."""
    
    @staticmethod
    def _get_achievements_collection():
        """Collection storing all achievement definitions."""
        return Database.get_collection("achievements")
    
    @staticmethod
    def _get_user_achievements_collection():
        """Collection mapping users to their unlocked achievements."""
        return Database.get_collection("user_achievements")
    
    @staticmethod
    def _get_plants_collection():
        return Database.get_collection("plants")
    
    @staticmethod
    def _get_stats_collection():
        return Database.get_collection("user_stats")
    
    @classmethod
    async def get_all_achievement_definitions(cls) -> List[Dict]:
        """Get all active achievement definitions from database."""
        collection = cls._get_achievements_collection()
        cursor = collection.find({"is_active": True})
        achievements = await cursor.to_list(length=100)
        return achievements
    
    @classmethod
    async def get_user_stats(cls, user_id: str) -> UserStats:
        """Get or create user stats."""
        stats_collection = cls._get_stats_collection()
        plants_collection = cls._get_plants_collection()
        
        # Get stored stats
        stored_stats = await stats_collection.find_one({"user_id": user_id})
        
        # Calculate live stats from plants
        plants = await plants_collection.find({"user_id": user_id}).to_list(length=1000)
        
        plant_count = len(plants)
        healthy_plants = len([p for p in plants if p.get("health_status") == "healthy"])
        max_streak = max((p.get("watering_streak", 0) for p in plants), default=0)
        unique_species = len(set(p.get("scientific_name", "") for p in plants if p.get("scientific_name")))
        
        # Get stored cumulative stats
        plants_revived = stored_stats.get("plants_revived", 0) if stored_stats else 0
        all_healthy_days = stored_stats.get("all_healthy_days", 0) if stored_stats else 0

        water_actions_count = (stored_stats or {}).get("water_actions_count")
        if water_actions_count is None:
            # Backfill from events as a safe baseline, then persist for future queries.
            try:
                events = Database.get_collection("events")
                water_actions_count = await events.count_documents(
                    {"user_id": user_id, "event_type": {"$in": list(WATERING_EVENT_TYPES)}}
                )
                await stats_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {"water_actions_count": int(water_actions_count), "updated_at": datetime.utcnow()},
                        "$setOnInsert": {"user_id": user_id, "created_at": datetime.utcnow()},
                    },
                    upsert=True,
                )
            except Exception:
                water_actions_count = 0

        water_on_time_count = int((stored_stats or {}).get("water_on_time_count", 0))
        water_early_count = int((stored_stats or {}).get("water_early_count", 0))
        water_late_count = int((stored_stats or {}).get("water_late_count", 0))
        
        return UserStats(
            plant_count=plant_count,
            healthy_plants=healthy_plants,
            total_waterings=int(water_actions_count or 0),
            max_streak=max_streak,
            unique_species=unique_species,
            water_actions_count=int(water_actions_count or 0),
            water_on_time_count=water_on_time_count,
            water_early_count=water_early_count,
            water_late_count=water_late_count,
            plants_revived=plants_revived,
            all_healthy_days=all_healthy_days,
        )

    @classmethod
    async def increment_watering_stats(cls, user_id: str, timing: Optional[str]) -> None:
        """
        Canonical watering counters used for achievements/stats.

        - water_actions_count always increments
        - one of water_on_time_count / water_early_count / water_late_count increments when timing is known
        """
        inc: Dict[str, int] = {"water_actions_count": 1}
        t = (timing or "").strip().lower()
        if t == "on_time":
            inc["water_on_time_count"] = 1
        elif t == "early":
            inc["water_early_count"] = 1
        elif t == "late":
            inc["water_late_count"] = 1

        stats_collection = cls._get_stats_collection()
        await stats_collection.update_one(
            {"user_id": user_id},
            {
                "$inc": inc,
                "$set": {"updated_at": datetime.utcnow()},
                "$setOnInsert": {"user_id": user_id, "created_at": datetime.utcnow()},
            },
            upsert=True,
        )
    
    @classmethod
    async def increment_stat(cls, user_id: str, stat_name: str, amount: int = 1) -> None:
        """Increment a cumulative stat (like plants_revived)."""
        stats_collection = cls._get_stats_collection()
        
        await stats_collection.update_one(
            {"user_id": user_id},
            {
                "$inc": {stat_name: amount},
                "$setOnInsert": {"user_id": user_id, "created_at": datetime.utcnow()}
            },
            upsert=True
        )
    
    @classmethod
    async def get_unlocked_achievements(cls, user_id: str) -> List[Dict]:
        """Get list of achievements the user has unlocked with timestamps."""
        collection = cls._get_user_achievements_collection()
        
        cursor = collection.find({"user_id": user_id})
        unlocked = await cursor.to_list(length=100)
        
        return unlocked
    
    @classmethod
    async def get_unlocked_achievement_ids(cls, user_id: str) -> List[str]:
        """Get list of achievement IDs the user has unlocked."""
        unlocked = await cls.get_unlocked_achievements(user_id)
        return [a["achievement_id"] for a in unlocked]
    
    @classmethod
    async def unlock_achievement(cls, user_id: str, achievement_id: str) -> bool:
        """Unlock an achievement for a user. Returns True if newly unlocked."""
        collection = cls._get_user_achievements_collection()
        
        # Check if already unlocked
        existing = await collection.find_one({
            "user_id": user_id,
            "achievement_id": achievement_id
        })
        
        if existing:
            return False
        
        # Unlock it
        await collection.insert_one({
            "user_id": user_id,
            "achievement_id": achievement_id,
            "unlocked_at": datetime.utcnow()
        })

        # Gamification: Add score for achievement unlock
        try:
            ach_def = await cls._get_achievements_collection().find_one({"id": achievement_id})
            if ach_def and "points" in ach_def:
                 from app.auth.service import AuthService
                 await AuthService.add_score(user_id, ach_def["points"])
        except Exception:
            pass
        
        return True
    
    @classmethod
    def check_achievement_condition(cls, achievement: Dict, stats: UserStats) -> Tuple[bool, float]:
        """
        Check if an achievement condition is met.
        Returns (is_unlocked, progress 0-1)
        """
        condition_type = achievement.get("condition_type")
        target_value = achievement.get("condition_value", 0)
        
        if not condition_type or target_value <= 0:
            return False, 0.0
        
        # Get current value based on condition type
        current_value = 0
        if condition_type == "plant_count":
            current_value = stats.plant_count
        elif condition_type == "healthy_plants":
            current_value = stats.healthy_plants
        elif condition_type == "total_waterings":
            current_value = stats.total_waterings
        elif condition_type == "max_streak":
            current_value = stats.max_streak
        elif condition_type == "unique_species":
            current_value = stats.unique_species
        elif condition_type == "plants_revived":
            current_value = stats.plants_revived
        elif condition_type == "all_healthy_days":
            current_value = stats.all_healthy_days
        
        progress = min(current_value / target_value, 1.0) if target_value > 0 else 0.0
        is_unlocked = current_value >= target_value
        
        return is_unlocked, progress
    
    @classmethod
    async def check_and_unlock_achievements(cls, user_id: str) -> List[Dict]:
        """
        Check all achievements and unlock any that are newly earned.
        Returns list of newly unlocked achievement details.
        """
        # Get all achievement definitions from database
        all_achievements = await cls.get_all_achievement_definitions()
        
        # Get current user stats
        stats = await cls.get_user_stats(user_id)
        
        # Get already unlocked
        unlocked_ids = await cls.get_unlocked_achievement_ids(user_id)
        
        newly_unlocked = []
        
        for achievement in all_achievements:
            achievement_id = achievement.get("id")
            
            if not achievement_id or achievement_id in unlocked_ids:
                continue
            
            is_earned, _ = cls.check_achievement_condition(achievement, stats)
            
            if is_earned:
                was_new = await cls.unlock_achievement(user_id, achievement_id)
                if was_new:
                    newly_unlocked.append({
                        "id": achievement_id,
                        "name": achievement.get("name"),
                        "description": achievement.get("description"),
                        "icon": achievement.get("icon"),
                        "points": achievement.get("points", 0),
                        "category": achievement.get("category"),
                        "tier": achievement.get("tier"),
                    })
        
        return newly_unlocked
    
    @classmethod
    async def get_all_achievements(cls, user_id: str) -> AchievementsListResponse:
        """Get all achievements with user's progress."""
        # Get all achievement definitions from database
        all_achievements = await cls.get_all_achievement_definitions()
        
        # Get user stats
        stats = await cls.get_user_stats(user_id)
        
        # Get user's unlocked achievements
        unlocked_list = await cls.get_unlocked_achievements(user_id)
        unlock_times = {a["achievement_id"]: a["unlocked_at"] for a in unlocked_list}
        unlocked_ids = set(unlock_times.keys())
        
        achievements = []
        total_points = 0
        
        for achievement in all_achievements:
            achievement_id = achievement.get("id")
            is_unlocked = achievement_id in unlocked_ids
            _, progress = cls.check_achievement_condition(achievement, stats)
            
            points = achievement.get("points", 0)
            if is_unlocked:
                total_points += points
            
            achievements.append(AchievementResponse(
                id=achievement_id,
                name=achievement.get("name", ""),
                description=achievement.get("description", ""),
                icon=achievement.get("icon", "🏆"),
                category=achievement.get("category", "collection"),
                tier=achievement.get("tier", "bronze"),
                points=points,
                unlocked=is_unlocked,
                unlocked_at=unlock_times.get(achievement_id),
                progress=progress if not is_unlocked else 1.0,
                condition_type=achievement.get("condition_type"),
                condition_value=achievement.get("condition_value"),
            ))
        
        # Sort: unlocked first, then by tier (bronze → silver → gold → platinum)
        tier_order = {"bronze": 0, "silver": 1, "gold": 2, "platinum": 3}
        achievements.sort(key=lambda a: (
            0 if a.unlocked else 1,
            tier_order.get(a.tier, 4),
            -a.progress
        ))
        
        return AchievementsListResponse(
            achievements=achievements,
            total_points=total_points,
            unlocked_count=len(unlocked_ids),
            total_count=len(all_achievements),
        )
