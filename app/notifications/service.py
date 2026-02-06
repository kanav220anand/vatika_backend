"""Notification service - handles notification CRUD and generation logic."""

from datetime import datetime, timedelta
from typing import Optional, List
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.database import Database
from app.core.exceptions import NotFoundException
from app.core.assets import public_asset_url
from app.notifications.models import (
    NotificationCreate,
    NotificationResponse,
    NotificationType,
    NotificationPriority,
)
from app.plants.watering_engine import compute_watering_recommendation


class NotificationService:
    """Handles notification-related database operations."""

    _ICON_PATHS = {
        "alert": "icons/notif_attention.svg",
        "info": "icons/notif_info.svg",
        "progress": "icons/notif_progress.svg",
        "reminder": "icons/notif_reminder.svg",
        "task": "icons/notif_task.svg",
        "water": "icons/notif_water.svg",
    }

    @classmethod
    def _icon_path_for_notification_type(cls, notification_type: str) -> str:
        """
        Map notification types to S3 icon paths.

        Rules provided:
        - alert -> icons/notif_attention.svg
        - info -> icons/notif_info.svg
        - progress -> icons/notif_progress.svg
        - reminders -> icons/notif_reminder.svg
        - task -> icons/notif_task.svg
        - water -> icons/notif_water.svg
        """
        t = (notification_type or "").strip().lower()
        if not t:
            return cls._ICON_PATHS["info"]

        # First, handle known v1 types explicitly.
        if t == NotificationType.WATER_REMINDER.value:
            return cls._ICON_PATHS["water"]
        if t == NotificationType.WATER_CHECK.value:
            return cls._ICON_PATHS["water"]
        if t == NotificationType.WATER_CHECK_SUMMARY.value:
            return cls._ICON_PATHS["water"]
        if t == NotificationType.ACTION_REQUIRED.value:
            return cls._ICON_PATHS["task"]
        if t in {NotificationType.HEALTH_ALERT.value, NotificationType.WEATHER_ALERT.value}:
            return cls._ICON_PATHS["alert"]

        # Heuristics for future/extended types (keeps old data working).
        if "water" in t:
            return cls._ICON_PATHS["water"]
        if "remind" in t:
            return cls._ICON_PATHS["reminder"]
        if "progress" in t or "achieve" in t or "level" in t:
            return cls._ICON_PATHS["progress"]
        if "task" in t or "action" in t:
            return cls._ICON_PATHS["task"]
        if "alert" in t or "health" in t or "weather" in t:
            return cls._ICON_PATHS["alert"]
        return cls._ICON_PATHS["info"]
    
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

        icon_path = cls._icon_path_for_notification_type(data.notification_type.value)
        doc = {
            "user_id": data.user_id,
            "notification_type": data.notification_type.value,
            "priority": data.priority.value,
            "title": data.title,
            "message": data.message,
            "icon_path": icon_path,
            "plant_id": data.plant_id,
            "action_url": data.action_url,
            "is_read": False,
            "created_at": datetime.utcnow(),
        }
        # Only include dedupe_key when set; otherwise it would store null and break sparse unique indexes.
        if data.dedupe_key:
            doc["dedupe_key"] = data.dedupe_key
        # Only include metadata when present; keep docs small.
        if data.metadata:
            doc["metadata"] = data.metadata
        
        result = await collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        
        return cls._doc_to_response(doc)

    @classmethod
    async def create_notification_deduped(cls, data: NotificationCreate) -> Optional[NotificationResponse]:
        """
        Create a notification, but return None if it already exists (dedupe_key unique).

        We intentionally avoid pre-check reads; the unique index is the source of truth.
        """
        try:
            return await cls.create_notification(data)
        except DuplicateKeyError:
            return None
    
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
    async def get_unread_count(cls, user_id: str) -> int:
        """Fast unread count for badge polling (no side effects)."""
        collection = cls._get_collection()
        return await collection.count_documents({"user_id": user_id, "is_read": False})
    
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
    async def generate_weather_alert(
        cls,
        user_id: str,
        alert_title: str,
        alert_message: str,
        severity: str = "medium",
    ) -> Optional[NotificationResponse]:
        """
        Generate a weather alert notification.

        Important: This must never raise outward; weather endpoints should not 500 due to side effects.
        """
        # Respect global user preference.
        try:
            user = await Database.get_collection("users").find_one(
                {"_id": ObjectId(user_id)},
                {"notifications_enabled": 1},
            )
            if user and user.get("notifications_enabled") is False:
                return None
        except Exception:
            # If user lookup fails, fail open (do not crash /weather endpoints).
            pass

        try:
            # Deduplicate to avoid spamming: same user + type + title within 6 hours.
            collection = cls._get_collection()
            now = datetime.utcnow()
            recent = await collection.find_one(
                {
                    "user_id": user_id,
                    "notification_type": NotificationType.WEATHER_ALERT.value,
                    "title": alert_title,
                    "created_at": {"$gte": now - timedelta(hours=6)},
                }
            )
            if recent:
                return None

            severity_norm = (severity or "").strip().lower()
            if severity_norm == "high":
                priority = NotificationPriority.HIGH
            elif severity_norm == "low":
                priority = NotificationPriority.LOW
            else:
                priority = NotificationPriority.MEDIUM

            return await cls.create_notification(
                NotificationCreate(
                    user_id=user_id,
                    notification_type=NotificationType.WEATHER_ALERT,
                    priority=priority,
                    title=alert_title,
                    message=alert_message,
                    action_url="/garden",
                )
            )
        except Exception:
            return None
    
    @classmethod
    async def check_watering_reminders(cls, user_id: str) -> List[NotificationResponse]:
        """
        Check all user's plants and generate watering reminders if needed.
        Called periodically or when user opens the app.
        """
        # Respect global user preference.
        try:
            user = await Database.get_collection("users").find_one({"_id": ObjectId(user_id)}, {"notifications_enabled": 1})
            if user and user.get("notifications_enabled") is False:
                return []
        except Exception:
            # If the user lookup fails, don't block reminders.
            pass

        plants_collection = cls._get_plants_collection()
        notifications = []
        
        now = datetime.utcnow()
        date_key = now.strftime("%Y-%m-%d")

        async def gather_actionable_plants() -> dict:
            """
            Action bucket hook for future signals (soil, etc.) without changing notification UX.

            Returns:
              - water_reminder_plants: list[dict] (schedule-based due/overdue)
              - unknown_history_plants: list[dict] (need "check soil" baseline)
              - soil_action_plants: list[dict] (placeholder for future soil hint integration)
            """
            buckets = {"water_reminder_plants": [], "unknown_history_plants": [], "soil_action_plants": []}

            cursor = plants_collection.find({"user_id": user_id, "reminders_enabled": {"$ne": False}})
            async for plant in cursor:
                last_watered = plant.get("last_watered")
                last_source = (plant.get("last_watered_source") or "").strip() or None
                unknown_history = last_watered is None and (last_source in (None, "unknown"))

                if unknown_history:
                    buckets["unknown_history_plants"].append(plant)
                    continue

                rec = compute_watering_recommendation(plant, now=now)
                if rec.urgency in {"due_today", "overdue"}:
                    # Attach rec so we don't recompute.
                    plant["_water_rec"] = rec
                    buckets["water_reminder_plants"].append(plant)

            return buckets

        buckets = await gather_actionable_plants()

        # A) Schedule-based per-plant reminders (due_today/overdue), once per plant per day.
        for plant in buckets["water_reminder_plants"]:
            plant_id = str(plant["_id"])
            plant_name = plant.get("nickname") or plant.get("common_name") or "Your plant"
            rec = plant.get("_water_rec") or compute_watering_recommendation(plant, now=now)

            dedupe_key = f"water_reminder:{user_id}:{plant_id}:{date_key}"
            notification = await cls.create_notification_deduped(
                NotificationCreate(
                    user_id=user_id,
                    notification_type=NotificationType.WATER_REMINDER,
                    priority=NotificationPriority.HIGH if rec.urgency == "overdue" else NotificationPriority.MEDIUM,
                    title="Time to water",
                    message=f"{plant_name}: {rec.recommended_action}. Remember to mark it as watered.",
                    plant_id=plant_id,
                    action_url=f"/plants/{plant_id}",
                    dedupe_key=dedupe_key,
                    metadata={
                        "plant_id": plant_id,
                        "urgency": rec.urgency,
                        "next_water_date": rec.next_water_date.isoformat() if rec.next_water_date else None,
                        "days_until_due": rec.days_until_due,
                    },
                )
            )
            if notification:
                notifications.append(notification)

        # B) Unknown last-watered reminders: one daily summary per user (no per-plant spam).
        unknown_plants = buckets["unknown_history_plants"]
        unknown_count = len(unknown_plants)
        if unknown_count > 0:
            plant_ids = [str(p["_id"]) for p in unknown_plants]
            sample_names = [
                (p.get("nickname") or p.get("common_name") or "Plant").strip()
                for p in unknown_plants[:3]
            ]
            title = "Check soil for your plants"
            if unknown_count == 1:
                body = "Check soil for 1 plant today. Water only if dry — and remember to mark it as watered."
            else:
                body = f"Check soil for {unknown_count} plants today. Water only if dry — and remember to mark them as watered."

            dedupe_key = f"water_check_summary:{user_id}:{date_key}"
            primary_plant_id = plant_ids[0] if plant_ids else None
            notification = await cls.create_notification_deduped(
                NotificationCreate(
                    user_id=user_id,
                    notification_type=NotificationType.WATER_CHECK_SUMMARY,
                    priority=NotificationPriority.MEDIUM,
                    title=title,
                    message=body,
                    # Optional compatibility: set a primary plant id for older clients that expect one.
                    plant_id=primary_plant_id,
                    action_url="/garden",
                    dedupe_key=dedupe_key,
                    metadata={
                        "count": unknown_count,
                        "plant_ids": plant_ids,
                        "sample_names": sample_names[:3],
                        "primary_plant_id": primary_plant_id,
                        "action_bucket": "unknown_history",
                    },
                )
            )
            if notification:
                notifications.append(notification)
        
        return notifications
    
    # ==================== Helpers ====================
    
    @staticmethod
    def _doc_to_response(doc: dict) -> NotificationResponse:
        """Convert MongoDB document to NotificationResponse."""
        icon_path = doc.get("icon_path")
        if not icon_path:
            # Back-compat for old docs created before icon support.
            icon_path = NotificationService._icon_path_for_notification_type(doc.get("notification_type", ""))
        return NotificationResponse(
            id=str(doc["_id"]),
            user_id=doc["user_id"],
            notification_type=doc["notification_type"],
            priority=doc["priority"],
            title=doc["title"],
            message=doc["message"],
            metadata=doc.get("metadata") or {},
            icon_url=public_asset_url(icon_path),
            image_url=doc.get("image_url"),
            plant_id=doc.get("plant_id"),
            plant_ids=doc.get("plant_ids") or [],
            primary_plant_id=doc.get("primary_plant_id"),
            action_url=doc.get("action_url"),
            state=doc.get("state", "sent"),
            is_read=doc.get("is_read", False),
            reminder_day=doc.get("reminder_day", 1),
            snoozed_until=doc.get("snoozed_until"),
            actioned_at=doc.get("actioned_at"),
            created_at=doc["created_at"],
        )
