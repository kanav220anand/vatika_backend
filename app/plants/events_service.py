"""Events service - append-only event logging for history and analytics."""

from datetime import datetime
from typing import Optional, Dict, Any
from bson import ObjectId

from app.core.database import Database


class EventType:
    """Event type constants."""
    WATERED = "watered"
    PLANT_WATERED = "plant_watered"  # legacy
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
        metadata: Optional[Dict[str, Any]] = None,
        occurred_at: Optional[datetime] = None,
    ) -> str:
        """
        Log an event to the events collection.
        
        Returns: ID of the created event.
        """
        collection = cls._get_collection()
        at = occurred_at or datetime.utcnow()
        doc = {
            "user_id": user_id,
            "event_type": event_type,
            "plant_id": plant_id,
            "metadata": metadata or {},
            "created_at": at,
            "occurred_at": at,
        }
        
        result = await collection.insert_one(doc)
        return str(result.inserted_id)

    @classmethod
    async def log_watering_event(
        cls,
        user_id: str,
        plant_id: str,
        occurred_at: datetime,
        recommended_at: Optional[datetime],
        timing: Optional[str],
        delta_days: Optional[int],
        streak_before: int,
        streak_after: int,
        next_water_date_before: Optional[datetime],
        next_water_date_after: Optional[datetime],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Log an enriched watering event for history rendering.

        All extra fields are optional/backward-compatible for older events.
        """
        collection = cls._get_collection()
        doc = {
            "user_id": user_id,
            "event_type": EventType.WATERED,
            "plant_id": plant_id,
            "metadata": {**(metadata or {}), "source": (metadata or {}).get("source", "user")},
            "created_at": occurred_at,
            "occurred_at": occurred_at,
            "recommended_at": recommended_at,
            "timing": timing,
            "delta_days": delta_days,
            "streak_before": int(streak_before or 0),
            "streak_after": int(streak_after or 0),
            "next_water_date_before": next_water_date_before,
            "next_water_date_after": next_water_date_after,
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
            occurred_at = doc.get("occurred_at") or doc.get("created_at")
            events.append({
                "id": str(doc["_id"]),
                "event_type": doc["event_type"],
                "plant_id": doc.get("plant_id"),
                "metadata": doc.get("metadata", {}),
                "created_at": doc["created_at"],
                "occurred_at": occurred_at,
                "recommended_at": doc.get("recommended_at"),
                "timing": doc.get("timing"),
                "delta_days": doc.get("delta_days"),
                "streak_before": doc.get("streak_before"),
                "streak_after": doc.get("streak_after"),
                "next_water_date_before": doc.get("next_water_date_before"),
                "next_water_date_after": doc.get("next_water_date_after"),
            })
        
        return events
