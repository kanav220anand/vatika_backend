"""
MongoDB database connection and utilities.
"""

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

        # Cities collection
        await cls.db.cities.create_index("name_lower", unique=True)
        await cls.db.cities.create_index("state_lower")
        await cls.db.cities.create_index("rank")
    
    @classmethod
    def get_collection(cls, name: str):
        """Get a collection by name."""
        return cls.db[name]


def get_db() -> AsyncIOMotorDatabase:
    """Get the database instance."""
    return Database.db
