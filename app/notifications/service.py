"""Notification service - handles notification CRUD and generation logic."""

from datetime import datetime, timedelta
from typing import Optional, List
from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import NotFoundException
from app.notifications.models import (
    NotificationCreate,
    NotificationResponse,
    NotificationType,
    NotificationPriority,
)


class NotificationService:
    """Handles notification-related database operations."""
    
    @staticmethod
    def _get_collection():
        return Database.get_collection("notifications")
    
    @staticmethod
    def _get_plants_collection():
        return Database.get_collection("plants")
    
    @staticmethod
    def _validate_object_id(id_str: str) -> ObjectId:
        """Validate and convert string to ObjectId."""
        if not ObjectId.is_valid(id_str):
            raise ValueError("Invalid ID")
        return ObjectId(id_str)
    
    # ==================== CRUD Operations ====================
    
    @classmethod
    async def create_notification(cls, data: NotificationCreate) -> NotificationResponse:
        """Create a new notification."""
        collection = cls._get_collection()
        
        doc = {
            "user_id": data.user_id,
            "notification_type": data.notification_type.value,
            "priority": data.priority.value,
            "title": data.title,
            "message": data.message,
            "plant_id": data.plant_id,
            "action_url": data.action_url,
            "is_read": False,
            "created_at": datetime.utcnow(),
        }
        
        result = await collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        
        return cls._doc_to_response(doc)
    
    @classmethod
    async def get_user_notifications(
        cls, 
        user_id: str, 
        limit: int = 50,
        include_read: bool = True
    ) -> tuple[List[NotificationResponse], int, int]:
        """
        Get notifications for a user.
        Returns: (notifications, total_count, unread_count)
        """
        collection = cls._get_collection()
        
        query = {"user_id": user_id}
        if not include_read:
            query["is_read"] = False
        
        # Get total and unread counts
        total_count = await collection.count_documents({"user_id": user_id})
        unread_count = await collection.count_documents({"user_id": user_id, "is_read": False})
        
        # Get notifications (unread first, then by date)
        cursor = collection.find(query).sort([
            ("is_read", 1),  # Unread first
            ("created_at", -1)  # Newest first
        ]).limit(limit)
        
        notifications = []
        async for doc in cursor:
            response = cls._doc_to_response(doc)
            # Get plant name if plant_id exists
            if doc.get("plant_id"):
                plant = await cls._get_plants_collection().find_one({
                    "_id": cls._validate_object_id(doc["plant_id"])
                })
                if plant:
                    response.plant_name = plant.get("common_name")
            notifications.append(response)
        
        return notifications, total_count, unread_count
    
    @classmethod
    async def mark_as_read(cls, notification_id: str, user_id: str) -> NotificationResponse:
        """Mark a notification as read."""
        collection = cls._get_collection()
        object_id = cls._validate_object_id(notification_id)
        
        result = await collection.find_one_and_update(
            {"_id": object_id, "user_id": user_id},
            {"$set": {"is_read": True}},
            return_document=True
        )
        
        if not result:
            raise NotFoundException("Notification not found")
        
        return cls._doc_to_response(result)
    
    @classmethod
    async def mark_all_as_read(cls, user_id: str) -> int:
        """Mark all user's notifications as read. Returns count updated."""
        collection = cls._get_collection()
        
        result = await collection.update_many(
            {"user_id": user_id, "is_read": False},
            {"$set": {"is_read": True}}
        )
        
        return result.modified_count
    
    @classmethod
    async def delete_notification(cls, notification_id: str, user_id: str) -> bool:
        """Delete a notification."""
        collection = cls._get_collection()
        object_id = cls._validate_object_id(notification_id)
        
        result = await collection.delete_one({
            "_id": object_id,
            "user_id": user_id
        })
        
        if result.deleted_count == 0:
            raise NotFoundException("Notification not found")
        
        return True
    
    # ==================== Notification Generation ====================
    
    @classmethod
    async def generate_health_notification(
        cls,
        user_id: str,
        plant_id: str,
        plant_name: str,
        health_status: str,
        issues: List[str] = None
    ) -> Optional[NotificationResponse]:
        """Generate a health alert notification for a plant."""
        if health_status == "healthy":
            return None
        
        # Check if similar notification already exists (within last 24h)
        collection = cls._get_collection()
        recent = await collection.find_one({
            "user_id": user_id,
            "plant_id": plant_id,
            "notification_type": NotificationType.HEALTH_ALERT.value,
            "created_at": {"$gte": datetime.utcnow() - timedelta(hours=24)}
        })
        
        if recent:
            return None  # Don't spam with duplicate notifications
        
        priority = NotificationPriority.HIGH if health_status == "unhealthy" else NotificationPriority.MEDIUM
        
        issue_text = ""
        if issues:
            issue_text = f": {', '.join(issues[:2])}"
        
        return await cls.create_notification(NotificationCreate(
            user_id=user_id,
            notification_type=NotificationType.HEALTH_ALERT,
            priority=priority,
            title=f"🌿 {plant_name} needs attention",
            message=f"Your plant is {health_status}{issue_text}. Check it soon!",
            plant_id=plant_id,
            action_url=f"/plants/{plant_id}"
        ))
    
    @classmethod
    async def generate_water_reminder(
        cls,
        user_id: str,
        plant_id: str,
        plant_name: str,
        days_since_watered: int
    ) -> Optional[NotificationResponse]:
        """Generate a watering reminder notification."""
        # Check if similar notification already exists (within last 12h)
        collection = cls._get_collection()
        recent = await collection.find_one({
            "user_id": user_id,
            "plant_id": plant_id,
            "notification_type": NotificationType.WATER_REMINDER.value,
            "created_at": {"$gte": datetime.utcnow() - timedelta(hours=12)}
        })
        
        if recent:
            return None
        
        priority = NotificationPriority.HIGH if days_since_watered > 7 else NotificationPriority.MEDIUM
        
        return await cls.create_notification(NotificationCreate(
            user_id=user_id,
            notification_type=NotificationType.WATER_REMINDER,
            priority=priority,
            title=f"💧 Time to water {plant_name}",
            message=f"It's been {days_since_watered} days since you last watered this plant.",
            plant_id=plant_id,
            action_url=f"/plants/{plant_id}"
        ))
    
    @classmethod
    async def generate_action_notification(
        cls,
        user_id: str,
        plant_id: str,
        plant_name: str,
        actions: List[str]
    ) -> Optional[NotificationResponse]:
        """Generate an action required notification from plant analysis."""
        if not actions:
            return None
        
        return await cls.create_notification(NotificationCreate(
            user_id=user_id,
            notification_type=NotificationType.ACTION_REQUIRED,
            priority=NotificationPriority.HIGH,
            title=f"⚡ Action needed for {plant_name}",
            message=actions[0] if len(actions) == 1 else f"{actions[0]} (+{len(actions)-1} more)",
            plant_id=plant_id,
            action_url=f"/plants/{plant_id}"
        ))
    
    @classmethod
    async def check_watering_reminders(cls, user_id: str) -> List[NotificationResponse]:
        """
        Check all user's plants and generate watering reminders if needed.
        Called periodically or when user opens the app.
        """
        plants_collection = cls._get_plants_collection()
        notifications = []
        
        # Find plants that might need watering
        cursor = plants_collection.find({"user_id": user_id})
        
        async for plant in cursor:
            last_watered = plant.get("last_watered")
            if not last_watered:
                continue
            
            days_since = (datetime.utcnow() - last_watered).days
            
            # Simple threshold: remind if > 3 days (can be made smarter with care schedule)
            if days_since >= 3:
                notification = await cls.generate_water_reminder(
                    user_id=user_id,
                    plant_id=str(plant["_id"]),
                    plant_name=plant.get("common_name", "Your plant"),
                    days_since_watered=days_since
                )
                if notification:
                    notifications.append(notification)
        
        return notifications
    
    # ==================== Helpers ====================
    
    @staticmethod
    def _doc_to_response(doc: dict) -> NotificationResponse:
        """Convert MongoDB document to NotificationResponse."""
        return NotificationResponse(
            id=str(doc["_id"]),
            user_id=doc["user_id"],
            notification_type=doc["notification_type"],
            priority=doc["priority"],
            title=doc["title"],
            message=doc["message"],
            plant_id=doc.get("plant_id"),
            action_url=doc.get("action_url"),
            is_read=doc.get("is_read", False),
            created_at=doc["created_at"],
        )
