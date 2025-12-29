"""Service layer for recommended plants."""

from app.core.database import Database


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
        beginner_only: bool = False
    ) -> tuple[list[dict], int, bool]:
        """
        Get paginated list of recommended plants.
        
        Returns:
            Tuple of (plants list, total count, has_more flag)
        """
        collection = cls.get_collection()
        
        # Build filter
        filter_query = {}
        if beginner_only:
            filter_query["is_beginner_friendly"] = True
        
        # Get total count
        total = await collection.count_documents(filter_query)
        
        # Get paginated results, sorted by order
        cursor = collection.find(filter_query).sort("order", 1).skip(skip).limit(limit)
        plants = await cursor.to_list(length=limit)
        
        # Convert ObjectId to string and remove _id
        for plant in plants:
            plant.pop("_id", None)
        
        # Calculate has_more
        has_more = (skip + len(plants)) < total
        
        return plants, total, has_more
    
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
