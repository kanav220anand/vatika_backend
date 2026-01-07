"""Events service - append-only event logging for analytics."""

from datetime import datetime
from typing import Optional, Dict, Any
from bson import ObjectId

from app.core.database import Database


class EventType:
    """Event type constants."""
    PLANT_WATERED = "plant_watered"
    HEALTH_CHECK = "health_check"
    PROGRESS_PHOTO = "progress_photo"
    REMINDER_SENT = "reminder_sent"
    PLANT_ADDED = "plant_added"
    PLANT_DELETED = "plant_deleted"


class EventService:
    """Handles event logging to events collection."""
    
    @staticmethod
    def _get_collection():
        return Database.get_collection("events")
    
    @classmethod
    async def log_event(
        cls,
        user_id: str,
        event_type: str,
        plant_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Log an event to the events collection.
        
        Returns: ID of the created event.
        """
        collection = cls._get_collection()
        
        doc = {
            "user_id": user_id,
            "event_type": event_type,
            "plant_id": plant_id,
            "metadata": metadata or {},
            "created_at": datetime.utcnow()
        }
        
        result = await collection.insert_one(doc)
        return str(result.inserted_id)
    
    @classmethod
    async def get_user_events(
        cls,
        user_id: str,
        event_type: Optional[str] = None,
        plant_id: Optional[str] = None,
        limit: int = 50
    ) -> list:
        """Get recent events for a user."""
        collection = cls._get_collection()
        
        query = {"user_id": user_id}
        if event_type:
            query["event_type"] = event_type
        if plant_id:
            query["plant_id"] = plant_id
        
        cursor = collection.find(query).sort("created_at", -1).limit(limit)
        
        events = []
        async for doc in cursor:
            events.append({
                "id": str(doc["_id"]),
                "event_type": doc["event_type"],
                "plant_id": doc.get("plant_id"),
                "metadata": doc.get("metadata", {}),
                "created_at": doc["created_at"]
            })
        
        return events
