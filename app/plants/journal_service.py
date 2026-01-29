"""Plant Journal Service - manages plant notes and journal entries."""

from datetime import datetime
from typing import Optional, List
from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import NotFoundException, BadRequestException
from app.plants.models import JournalEntryCreate, JournalEntryUpdate, JournalEntry
from app.core.aws import S3Service


class JournalService:
    """Service for managing plant journal entries."""

    COLLECTION_NAME = "plant_journal"

    @classmethod
    def _get_collection(cls):
        return Database.get_collection(cls.COLLECTION_NAME)

    @classmethod
    def _validate_object_id(cls, id_str: str) -> ObjectId:
        try:
            return ObjectId(id_str)
        except Exception:
            raise BadRequestException(f"Invalid ID format: {id_str}")

    @classmethod
    async def create_entry(
        cls,
        plant_id: str,
        user_id: str,
        entry: JournalEntryCreate,
    ) -> JournalEntry:
        """Create a new journal entry for a plant."""
        collection = cls._get_collection()

        # Validate plant_id format
        cls._validate_object_id(plant_id)

        # Validate image_key ownership if provided
        image_url = None
        if entry.image_key:
            if not entry.image_key.startswith(f"plants/{user_id}/"):
                raise BadRequestException("Invalid image key")
            s3 = S3Service()
            image_url = s3.generate_presigned_get_url(entry.image_key, expiration=86400 * 7)

        doc = {
            "plant_id": plant_id,
            "user_id": user_id,
            "entry_type": entry.entry_type.value,
            "content": entry.content.strip(),
            "image_key": entry.image_key,
            "created_at": datetime.utcnow(),
            "updated_at": None,
        }

        result = await collection.insert_one(doc)
        doc["_id"] = result.inserted_id

        return JournalEntry(
            id=str(doc["_id"]),
            plant_id=doc["plant_id"],
            user_id=doc["user_id"],
            entry_type=doc["entry_type"],
            content=doc["content"],
            image_url=image_url,
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    @classmethod
    async def get_entries(
        cls,
        plant_id: str,
        user_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[JournalEntry], int, bool]:
        """Get journal entries for a plant with pagination."""
        collection = cls._get_collection()
        cls._validate_object_id(plant_id)

        query = {"plant_id": plant_id, "user_id": user_id}
        
        # Get total count
        total_count = await collection.count_documents(query)
        
        # Get entries (newest first)
        cursor = collection.find(query).sort("created_at", -1).skip(skip).limit(limit + 1)
        docs = await cursor.to_list(length=limit + 1)
        
        has_more = len(docs) > limit
        if has_more:
            docs = docs[:limit]

        s3 = S3Service()
        entries = []
        for doc in docs:
            image_url = None
            if doc.get("image_key"):
                image_url = s3.generate_presigned_get_url(doc["image_key"], expiration=3600)
            
            entries.append(JournalEntry(
                id=str(doc["_id"]),
                plant_id=doc["plant_id"],
                user_id=doc["user_id"],
                entry_type=doc["entry_type"],
                content=doc["content"],
                image_url=image_url,
                created_at=doc["created_at"],
                updated_at=doc.get("updated_at"),
            ))

        return entries, total_count, has_more

    @classmethod
    async def get_entry(cls, entry_id: str, user_id: str) -> JournalEntry:
        """Get a single journal entry."""
        collection = cls._get_collection()
        object_id = cls._validate_object_id(entry_id)

        doc = await collection.find_one({"_id": object_id, "user_id": user_id})
        if not doc:
            raise NotFoundException("Journal entry not found")

        s3 = S3Service()
        image_url = None
        if doc.get("image_key"):
            image_url = s3.generate_presigned_get_url(doc["image_key"], expiration=3600)

        return JournalEntry(
            id=str(doc["_id"]),
            plant_id=doc["plant_id"],
            user_id=doc["user_id"],
            entry_type=doc["entry_type"],
            content=doc["content"],
            image_url=image_url,
            created_at=doc["created_at"],
            updated_at=doc.get("updated_at"),
        )

    @classmethod
    async def update_entry(
        cls,
        entry_id: str,
        user_id: str,
        update: JournalEntryUpdate,
    ) -> JournalEntry:
        """Update a journal entry."""
        collection = cls._get_collection()
        object_id = cls._validate_object_id(entry_id)

        # Check ownership
        doc = await collection.find_one({"_id": object_id, "user_id": user_id})
        if not doc:
            raise NotFoundException("Journal entry not found")

        update_data = {"updated_at": datetime.utcnow()}
        if update.content is not None:
            update_data["content"] = update.content.strip()
        if update.entry_type is not None:
            update_data["entry_type"] = update.entry_type.value

        await collection.update_one({"_id": object_id}, {"$set": update_data})
        
        return await cls.get_entry(entry_id, user_id)

    @classmethod
    async def delete_entry(cls, entry_id: str, user_id: str) -> None:
        """Delete a journal entry."""
        collection = cls._get_collection()
        object_id = cls._validate_object_id(entry_id)

        # Check ownership and get image key for cleanup
        doc = await collection.find_one({"_id": object_id, "user_id": user_id})
        if not doc:
            raise NotFoundException("Journal entry not found")

        # Delete from DB
        await collection.delete_one({"_id": object_id})

        # Optionally delete image from S3
        if doc.get("image_key"):
            try:
                s3 = S3Service()
                s3.delete_object(doc["image_key"])
            except Exception:
                pass  # Best effort cleanup

    @classmethod
    async def get_recent_entries_all_plants(
        cls,
        user_id: str,
        limit: int = 10,
    ) -> List[JournalEntry]:
        """Get recent journal entries across all user's plants."""
        collection = cls._get_collection()
        
        cursor = collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)

        s3 = S3Service()
        entries = []
        for doc in docs:
            image_url = None
            if doc.get("image_key"):
                image_url = s3.generate_presigned_get_url(doc["image_key"], expiration=3600)
            
            entries.append(JournalEntry(
                id=str(doc["_id"]),
                plant_id=doc["plant_id"],
                user_id=doc["user_id"],
                entry_type=doc["entry_type"],
                content=doc["content"],
                image_url=image_url,
                created_at=doc["created_at"],
                updated_at=doc.get("updated_at"),
            ))

        return entries

    @classmethod
    async def ensure_indexes(cls) -> None:
        """Create necessary indexes for the collection."""
        collection = cls._get_collection()
        await collection.create_index([("plant_id", 1), ("user_id", 1)])
        await collection.create_index([("user_id", 1), ("created_at", -1)])
