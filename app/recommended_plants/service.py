"""Service layer for recommended plants."""

from typing import Optional, Literal
from fastapi import HTTPException
from app.core.database import Database
from app.wishlist.service import WishlistService


# Difficulty sort order mapping
DIFFICULTY_ORDER = {"easy": 1, "medium": 2, "hard": 3}


class RecommendedPlantsService:
    """Service for managing recommended plants."""
    
    @staticmethod
    def get_collection():
        """Get the recommended_plants collection."""
        return Database.get_collection("recommended_plants")
    
    @classmethod
    async def get_plants(
        cls,
        skip: int = 0,
        limit: int = 10,
        beginner_only: bool = False,
        wishlisted_only: bool = False,
        user_id: Optional[str] = None,
        difficulty: Optional[Literal["easy", "medium", "hard"]] = None,
        light_needs: Optional[Literal["low", "medium", "bright"]] = None,
        sort_by: Optional[Literal["name", "difficulty", "popularity"]] = None,
        sort_order: Optional[Literal["asc", "desc"]] = "asc"
    ) -> tuple[list[dict], int, bool]:
        """
        Get paginated list of recommended plants with filters and sorting.
        
        Returns:
            Tuple of (plants list, total count, has_more flag)
        """
        collection = cls.get_collection()
        
        # Build filter
        filter_query = {}
        if beginner_only:
            filter_query["is_beginner_friendly"] = True
        if wishlisted_only:
            # Wishlist is user-specific; if not authenticated, return no results.
            if not user_id:
                return [], 0, False
            plant_ids = await WishlistService.get_wishlist_plant_ids(user_id)
            filter_query["plant_id"] = {"$in": list(plant_ids)}
        if difficulty:
            filter_query["difficulty"] = difficulty
        if light_needs:
            filter_query["light_needs"] = light_needs
        
        # Get total count
        total = await collection.count_documents(filter_query)
        
        # Determine sort field and direction
        sort_direction = 1 if sort_order == "asc" else -1
        
        if sort_by == "name":
            sort_field = "common_name"
        elif sort_by == "difficulty":
            # For difficulty sorting, we'll use a custom approach
            sort_field = "order"  # fallback, we'll handle difficulty separately
        elif sort_by == "popularity":
            sort_field = "success_rate"
            # Higher success rate = more popular, so reverse for "asc"
            sort_direction = -1 if sort_order == "asc" else 1
        else:
            sort_field = "order"
        
        # Get paginated results
        cursor = collection.find(filter_query).sort(sort_field, sort_direction).skip(skip).limit(limit)
        plants = await cursor.to_list(length=limit)
        
        # If sorting by difficulty, sort in Python (since it's categorical)
        if sort_by == "difficulty":
            plants.sort(
                key=lambda p: DIFFICULTY_ORDER.get(p.get("difficulty", "medium"), 2),
                reverse=(sort_order == "desc")
            )
        
        # Convert ObjectId to string and remove _id
        for plant in plants:
            plant.pop("_id", None)
        
        # Calculate has_more
        has_more = (skip + len(plants)) < total
        
        return plants, total, has_more
    
    @classmethod
    async def get_plant_by_id(cls, plant_id: str) -> dict:
        """Get a single recommended plant by ID."""
        collection = cls.get_collection()
        plant = await collection.find_one({"plant_id": plant_id})
        
        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")
        
        plant.pop("_id", None)
        return plant
    
    @classmethod
    async def create_plant(cls, plant_data: dict) -> dict:
        """Create a new recommended plant."""
        collection = cls.get_collection()
        await collection.insert_one(plant_data)
        plant_data.pop("_id", None)
        return plant_data
    
    @classmethod
    async def count_plants(cls) -> int:
        """Get total count of recommended plants."""
        collection = cls.get_collection()
        return await collection.count_documents({})
