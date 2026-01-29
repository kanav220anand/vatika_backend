"""Service layer for user plant wishlist."""

from datetime import datetime
from typing import Optional
from app.core.database import Database


class WishlistService:
    """Service for managing user plant wishlists."""
    
    COLLECTION_NAME = "user_plant_wishlist"
    
    @staticmethod
    def get_collection():
        """Get the user_plant_wishlist collection."""
        return Database.get_collection(WishlistService.COLLECTION_NAME)
    
    @classmethod
    async def get_user_wishlist(cls, user_id: str) -> list[dict]:
        """
        Get all wishlist items for a user.
        
        Returns list of wishlist items sorted by added_at (newest first).
        """
        collection = cls.get_collection()
        cursor = collection.find({"user_id": user_id}).sort("added_at", -1)
        items = await cursor.to_list(length=100)  # Limit to 100 items
        
        # Remove MongoDB _id and user_id from response
        for item in items:
            item.pop("_id", None)
            item.pop("user_id", None)
        
        return items
    
    @classmethod
    async def get_wishlist_plant_ids(cls, user_id: str) -> set[str]:
        """
        Get just the plant IDs in a user's wishlist (for quick lookup).
        """
        collection = cls.get_collection()
        cursor = collection.find({"user_id": user_id}, {"plant_id": 1})
        items = await cursor.to_list(length=100)
        return {item["plant_id"] for item in items}
    
    @classmethod
    async def is_wishlisted(cls, user_id: str, plant_id: str) -> bool:
        """Check if a plant is in the user's wishlist."""
        collection = cls.get_collection()
        item = await collection.find_one({"user_id": user_id, "plant_id": plant_id})
        return item is not None
    
    @classmethod
    async def add_to_wishlist(cls, user_id: str, plant_data: dict) -> dict:
        """
        Add a plant to the user's wishlist.
        
        Returns the created wishlist item.
        """
        collection = cls.get_collection()
        
        # Check if already wishlisted
        existing = await collection.find_one({
            "user_id": user_id,
            "plant_id": plant_data["plant_id"]
        })
        
        if existing:
            # Already exists, return existing item
            existing.pop("_id", None)
            existing.pop("user_id", None)
            return existing
        
        # Create new wishlist item
        wishlist_item = {
            "user_id": user_id,
            "plant_id": plant_data["plant_id"],
            "common_name": plant_data["common_name"],
            "scientific_name": plant_data["scientific_name"],
            "image_url": plant_data.get("image_url"),
            "difficulty": plant_data["difficulty"],
            "price_range": plant_data.get("price_range"),
            "added_at": datetime.utcnow(),
        }
        
        await collection.insert_one(wishlist_item)
        
        # Return without _id and user_id
        wishlist_item.pop("_id", None)
        wishlist_item.pop("user_id", None)
        
        return wishlist_item
    
    @classmethod
    async def remove_from_wishlist(cls, user_id: str, plant_id: str) -> bool:
        """
        Remove a plant from the user's wishlist.
        
        Returns True if item was removed, False if it didn't exist.
        """
        collection = cls.get_collection()
        result = await collection.delete_one({
            "user_id": user_id,
            "plant_id": plant_id
        })
        return result.deleted_count > 0
    
    @classmethod
    async def toggle_wishlist(cls, user_id: str, plant_data: dict) -> tuple[bool, str]:
        """
        Toggle a plant in/out of the user's wishlist.
        
        Returns tuple of (is_now_wishlisted, message).
        """
        is_wishlisted = await cls.is_wishlisted(user_id, plant_data["plant_id"])
        
        if is_wishlisted:
            await cls.remove_from_wishlist(user_id, plant_data["plant_id"])
            return False, "Removed from wishlist"
        else:
            await cls.add_to_wishlist(user_id, plant_data)
            return True, "Added to wishlist"
    
    @classmethod
    async def clear_user_wishlist(cls, user_id: str) -> int:
        """
        Clear all items from a user's wishlist.
        
        Returns the number of items deleted.
        """
        collection = cls.get_collection()
        result = await collection.delete_many({"user_id": user_id})
        return result.deleted_count
    
    @classmethod
    async def count_user_wishlist(cls, user_id: str) -> int:
        """Get the count of items in a user's wishlist."""
        collection = cls.get_collection()
        return await collection.count_documents({"user_id": user_id})
    
    @classmethod
    async def ensure_indexes(cls):
        """Create indexes for efficient queries."""
        collection = cls.get_collection()
        # Compound index for user + plant (uniqueness)
        await collection.create_index(
            [("user_id", 1), ("plant_id", 1)],
            unique=True,
            name="user_plant_unique"
        )
        # Index for user queries
        await collection.create_index("user_id", name="user_id_idx")
