"""Gamification service - Level calculations and operations."""

from typing import List, Optional
from app.core.database import Database
from app.core.assets import public_asset_url
from app.gamification.models import LevelResponse, UserLevelResponse


class GamificationService:
    """Handles gamification operations - levels, points, etc."""
    
    _levels_cache: Optional[List[dict]] = None

    @staticmethod
    def _normalize_level_doc(level: dict) -> dict:
        """Remove Mongo-only fields and expand public asset URLs."""
        if not level:
            return {}

        doc = {k: v for k, v in level.items() if k != "_id"}
        if doc.get("badge_image_url"):
            doc["badge_image_url"] = public_asset_url(doc["badge_image_url"])
        if doc.get("perks") is None:
            doc["perks"] = []
        return doc
    
    @classmethod
    def _get_collection(cls):
        return Database.get_collection("user_levels")
    
    @classmethod
    async def get_all_levels(cls, use_cache: bool = True) -> List[LevelResponse]:
        """
        Fetch all active levels from the database.
        Results are cached for performance.
        """
        if use_cache and cls._levels_cache is not None:
            return [LevelResponse(**level) for level in cls._levels_cache]
        
        collection = cls._get_collection()
        cursor = collection.find(
            {"is_active": True}
        ).sort("sort_order", 1)
        
        levels = await cursor.to_list(length=100)
        normalized = [cls._normalize_level_doc(level) for level in levels]
        cls._levels_cache = normalized
        
        return [LevelResponse(**level) for level in normalized]
    
    @classmethod
    async def get_level_for_points(cls, points: int) -> Optional[dict]:
        """
        Find the level that matches the given points.
        Returns the raw level document.
        """
        levels = await cls.get_all_levels(use_cache=True)
        for lvl in levels:
            if points >= lvl.min_points and (lvl.max_points is None or points <= lvl.max_points):
                return lvl.model_dump()

        if levels:
            return levels[0].model_dump()
        return None
    
    @classmethod
    async def calculate_user_level(cls, points: int) -> UserLevelResponse:
        """
        Calculate user's level info based on their points.
        Returns complete level info with progress.
        """
        current_level = await cls.get_level_for_points(points)
        
        if not current_level:
            # Fallback to level 1 if no match found
            all_levels = await cls.get_all_levels()
            if all_levels:
                current_level = all_levels[0].model_dump()
            else:
                # Emergency fallback
                return UserLevelResponse(
                    level=1,
                    title="Seed",
                    icon="🫘",
                    color="#8B5A2B",
                    current_points=points,
                    points_to_next_level=100,
                    progress_percent=0.0
                )
        
        # Calculate progress
        min_points = current_level["min_points"]
        max_points = current_level.get("max_points")
        
        if max_points is None:
            # At max level
            progress_percent = 100.0
            points_to_next = None
            next_title = None
        else:
            range_size = max_points - min_points + 1
            progress_in_range = points - min_points
            progress_percent = min(100.0, (progress_in_range / range_size) * 100)
            points_to_next = max_points - points + 1
            
            # Get next level title
            all_levels = await cls.get_all_levels(use_cache=True)
            next_level = next((l for l in all_levels if l.level == current_level["level"] + 1), None)
            next_title = next_level.title if next_level else None
        
        return UserLevelResponse(
            level=current_level["level"],
            title=current_level["title"],
            icon=current_level["icon"],
            color=current_level["color"],
            current_points=points,
            points_to_next_level=points_to_next,
            progress_percent=round(progress_percent, 1),
            next_level_title=next_title
        )
    
    @classmethod
    def clear_cache(cls):
        """Clear the levels cache (call after updating levels)."""
        cls._levels_cache = None
