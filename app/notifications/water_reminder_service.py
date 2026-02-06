"""
Water Reminder Service

This module handles the core business logic for water reminder notifications.
Implements the complete water reminder system including:
- Daily batched reminders at 8 AM IST
- Escalating message urgency over 5 days
- Snooze functionality (4 hours or tomorrow morning)
- State machine for notification lifecycle
- Different behavior for ignored vs snoozed notifications

Key Design Decisions:
- One notification per user per morning (batched if multiple plants)
- Most overdue plant featured first in batched notifications
- Snooze is intentional postponement (sends push at snoozed time)
- Ignore is passive (respects user's silence after 5 days)
- State machine tracks: sent → delivered → opened → actioned/snoozed/dismissed/expired
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import pytz

from app.core.database import Database
from app.core.config import get_settings
from app.notifications.models import (
    NotificationType,
    NotificationPriority,
    NotificationState,
    NotificationCreate,
)
from app.notifications.content import WaterReminderContent
from app.plants.watering_engine import compute_watering_recommendation

logger = logging.getLogger(__name__)


class WaterReminderService:
    """
    Service for managing water reminder notifications.
    
    This service handles:
    - Generating daily water reminders (single plant or batched)
    - Tracking reminder state and escalation
    - Processing user actions (watered, snooze, dismiss)
    - Respecting user silence after max reminder days
    """
    
    # -------------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------------
    
    # IST timezone for scheduling
    IST = pytz.timezone("Asia/Kolkata")
    
    @classmethod
    def _get_settings(cls):
        """Get application settings."""
        return get_settings()
    
    @classmethod
    def _get_notifications_collection(cls):
        """Get notifications MongoDB collection."""
        return Database.get_collection("notifications")
    
    @classmethod
    def _get_plants_collection(cls):
        """Get plants MongoDB collection."""
        return Database.get_collection("plants")
    
    @classmethod
    def _get_users_collection(cls):
        """Get users MongoDB collection."""
        return Database.get_collection("users")
    
    @classmethod
    def _get_reminder_state_collection(cls):
        """
        Get water reminder state collection.
        
        This collection tracks per-plant reminder state:
        - How many consecutive days we've sent reminders
        - Whether the user has snoozed or ignored
        - When to resume reminders after ignore pause
        """
        return Database.get_collection("water_reminder_state")
    
    # -------------------------------------------------------------------------
    # Main Entry Point: Daily Reminder Generation
    # -------------------------------------------------------------------------
    
    @classmethod
    async def generate_daily_reminders(cls) -> Dict[str, int]:
        """
        Generate water reminders for all users.
        
        This is the main entry point called by the Celery beat scheduler
        at 8 AM IST daily.
        
        Returns:
            Dict with counts: {
                "users_processed": int,
                "notifications_created": int,
                "plants_needing_water": int,
                "users_skipped": int
            }
        """
        settings = cls._get_settings()
        users_collection = cls._get_users_collection()
        
        stats = {
            "users_processed": 0,
            "notifications_created": 0,
            "plants_needing_water": 0,
            "users_skipped": 0,
        }
        
        # Get all users with notifications enabled
        cursor = users_collection.find(
            {"notifications_enabled": {"$ne": False}},
            {"_id": 1, "name": 1, "email": 1}
        )
        
        async for user in cursor:
            user_id = str(user["_id"])
            try:
                result = await cls.generate_user_water_reminder(user_id)
                stats["users_processed"] += 1
                if result:
                    stats["notifications_created"] += 1
                    stats["plants_needing_water"] += result.get("plant_count", 0)
                else:
                    stats["users_skipped"] += 1
            except Exception as e:
                logger.error(f"Failed to generate reminder for user {user_id}: {e}")
                stats["users_skipped"] += 1
        
        logger.info(f"Daily water reminders complete: {stats}")
        return stats
    
    @classmethod
    async def generate_user_water_reminder(cls, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Generate a water reminder notification for a specific user.
        
        Logic:
        1. Find all plants needing water (due_today or overdue)
        2. Filter out plants with paused reminders (ignored for 5+ days)
        3. Batch into single notification if multiple plants
        4. Use escalating messages based on reminder day
        5. Feature most overdue plant first
        
        Args:
            user_id: User's MongoDB ObjectId string.
            
        Returns:
            Dict with notification details if created, None if no reminder needed.
        """
        settings = cls._get_settings()
        now = datetime.utcnow()
        date_key = now.strftime("%Y-%m-%d")
        
        # Check for existing notification today (deduplication)
        existing = await cls._get_notifications_collection().find_one({
            "user_id": user_id,
            "notification_type": NotificationType.WATER_REMINDER.value,
            "dedupe_key": f"water_reminder_daily:{user_id}:{date_key}"
        })
        if existing:
            logger.debug(f"User {user_id} already has water reminder for {date_key}")
            return None
        
        # Gather plants needing water
        plants_needing_water = await cls._get_plants_needing_water(user_id, now)
        
        if not plants_needing_water:
            logger.debug(f"User {user_id} has no plants needing water")
            return None
        
        # Sort by most overdue first
        plants_sorted = await cls._sort_plants_by_urgency(plants_needing_water, now)
        
        # Get reminder state for the most overdue plant
        primary_plant = plants_sorted[0]
        reminder_state = await cls._get_or_create_reminder_state(
            user_id, 
            str(primary_plant["_id"])
        )
        
        # Check if we should pause reminders (ignored for max days)
        if await cls._should_pause_reminders(reminder_state):
            logger.debug(f"Reminders paused for user {user_id} plant {primary_plant['_id']}")
            return None
        
        # Determine reminder day (for message escalation)
        reminder_day = min(reminder_state.get("consecutive_days", 0) + 1, 5)
        
        # Create the notification
        notification_data = await cls._create_water_notification(
            user_id=user_id,
            plants=plants_sorted,
            reminder_day=reminder_day,
            date_key=date_key
        )
        
        # Update reminder state
        await cls._update_reminder_state(
            user_id=user_id,
            plant_id=str(primary_plant["_id"]),
            action="sent",
            reminder_day=reminder_day
        )
        
        return {
            "notification_id": notification_data.get("id"),
            "plant_count": len(plants_sorted),
            "primary_plant": primary_plant.get("common_name"),
            "reminder_day": reminder_day
        }
    
    # -------------------------------------------------------------------------
    # Plant Data Gathering
    # -------------------------------------------------------------------------
    
    @classmethod
    async def _get_plants_needing_water(
        cls, 
        user_id: str, 
        now: datetime
    ) -> List[Dict[str, Any]]:
        """
        Get all plants for a user that need watering today.
        
        Criteria:
        - Plant belongs to user
        - Reminders are enabled for plant
        - Watering recommendation is "due_today" or "overdue"
        - Reminder state is not paused
        
        Args:
            user_id: User's MongoDB ObjectId string.
            now: Current datetime for recommendation calculation.
            
        Returns:
            List of plant documents needing water.
        """
        plants_collection = cls._get_plants_collection()
        plants_needing_water = []
        
        cursor = plants_collection.find({
            "user_id": user_id,
            "reminders_enabled": {"$ne": False}
        })
        
        async for plant in cursor:
            # Compute watering recommendation
            rec = compute_watering_recommendation(plant, now=now)
            
            if rec.urgency in {"due_today", "overdue"}:
                # Check if reminder state is not paused
                plant_id = str(plant["_id"])
                reminder_state = await cls._get_reminder_state(user_id, plant_id)
                
                if reminder_state and await cls._should_pause_reminders(reminder_state):
                    continue
                
                # Attach recommendation for sorting
                plant["_water_rec"] = rec
                plants_needing_water.append(plant)
        
        return plants_needing_water
    
    @classmethod
    async def _sort_plants_by_urgency(
        cls, 
        plants: List[Dict[str, Any]], 
        now: datetime
    ) -> List[Dict[str, Any]]:
        """
        Sort plants by urgency (most overdue first).
        
        Sorting criteria:
        1. Days overdue (descending)
        2. Last watered date (oldest first)
        3. Plant name (alphabetical tie-breaker)
        
        Args:
            plants: List of plant documents with _water_rec attached.
            now: Current datetime for comparison.
            
        Returns:
            Sorted list of plants.
        """
        def sort_key(plant: Dict[str, Any]) -> Tuple:
            rec = plant.get("_water_rec")
            days_overdue = 0
            if rec and rec.days_until_due is not None:
                days_overdue = -rec.days_until_due  # Negative for overdue
            
            last_watered = plant.get("last_watered") or datetime.min
            name = plant.get("nickname") or plant.get("common_name") or ""
            
            return (-days_overdue, last_watered, name.lower())
        
        return sorted(plants, key=sort_key, reverse=True)
    
    # -------------------------------------------------------------------------
    # Notification Creation
    # -------------------------------------------------------------------------
    
    @classmethod
    async def _create_water_notification(
        cls,
        user_id: str,
        plants: List[Dict[str, Any]],
        reminder_day: int,
        date_key: str
    ) -> Dict[str, Any]:
        """
        Create a water reminder notification.
        
        Single plant: Shows specific plant message with "Watered" CTA.
        Multiple plants: Shows batched message with "View plants" CTA.
        
        Args:
            user_id: User's MongoDB ObjectId string.
            plants: List of plants needing water (sorted by urgency).
            reminder_day: Which day of reminder sequence (1-5).
            date_key: Date string for deduplication.
            
        Returns:
            Created notification document.
        """
        settings = cls._get_settings()
        notifications_collection = cls._get_notifications_collection()
        
        primary_plant = plants[0]
        primary_plant_id = str(primary_plant["_id"])
        primary_plant_name = (
            primary_plant.get("nickname") or 
            primary_plant.get("common_name") or 
            "Your plant"
        )
        
        plant_count = len(plants)
        other_count = plant_count - 1
        batch_cap = settings.WATER_REMINDER_BATCH_CAP
        
        # Get title based on reminder day
        title = WaterReminderContent.get_title(reminder_day)
        
        # Generate message based on single vs multiple plants
        if plant_count == 1:
            message = WaterReminderContent.single_plant_message(
                primary_plant_name, 
                reminder_day
            )
            plant_ids = [primary_plant_id]
            action_url = f"/plants/{primary_plant_id}"
            cta_type = "watered"  # Single plant shows "Watered" button
        else:
            # Cap the "other" count for display
            display_count = min(other_count, batch_cap)
            capped = other_count > batch_cap
            
            message = WaterReminderContent.multiple_plants_message(
                primary_plant_name,
                display_count,
                reminder_day,
                capped=capped
            )
            plant_ids = [str(p["_id"]) for p in plants]
            action_url = "/care"  # Opens grouped care screen
            cta_type = "view_plants"  # Multiple plants show "View plants" button
        
        # Determine image URL
        image_url = await cls._get_notification_image(plants)
        
        # Build notification document
        doc = {
            "user_id": user_id,
            "notification_type": NotificationType.WATER_REMINDER.value,
            "priority": NotificationPriority.MEDIUM.value,
            "title": title,
            "message": message,
            "image_url": image_url,
            "icon_path": "icons/notif_water.svg",
            
            # Plant references
            "plant_id": primary_plant_id,
            "plant_ids": plant_ids,
            "primary_plant_id": primary_plant_id,
            
            # State machine
            "state": NotificationState.SENT.value,
            "reminder_day": reminder_day,
            "is_read": False,
            "snoozed_until": None,
            "actioned_at": None,
            
            # Deep link
            "action_url": action_url,
            
            # Deduplication
            "dedupe_key": f"water_reminder_daily:{user_id}:{date_key}",
            
            # Metadata for frontend
            "metadata": {
                "plant_count": plant_count,
                "cta_type": cta_type,
                "plant_names": [
                    (p.get("nickname") or p.get("common_name") or "Plant")[:30]
                    for p in plants[:5]  # First 5 plant names
                ],
                "reminder_day": reminder_day,
                "urgencies": {
                    str(p["_id"]): p.get("_water_rec").urgency 
                    for p in plants 
                    if p.get("_water_rec")
                }
            },
            
            "created_at": datetime.utcnow(),
        }
        
        result = await notifications_collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        
        logger.info(
            f"Created water reminder for user {user_id}: "
            f"{plant_count} plants, day {reminder_day}"
        )
        
        return {"id": str(result.inserted_id), **doc}
    
    @classmethod
    async def _get_notification_image(cls, plants: List[Dict[str, Any]]) -> str:
        """
        Determine which image to use for the notification.
        
        Rules:
        - Single plant with image: Use plant's S3 image
        - Multiple plants: Use Vatisha logo
        - No plant image available: Use Vatisha logo
        
        Args:
            plants: List of plants in the notification.
            
        Returns:
            S3 URL for the notification image.
        """
        settings = cls._get_settings()
        logo_url = settings.VATISHA_NOTIFICATION_LOGO_URL
        
        if len(plants) == 1:
            # Single plant - try to use plant image
            plant = plants[0]
            plant_image = plant.get("image_url")
            if plant_image:
                return plant_image
        
        # Multiple plants or no plant image - use Vatisha logo
        return logo_url or ""
    
    # -------------------------------------------------------------------------
    # Reminder State Management
    # -------------------------------------------------------------------------
    
    @classmethod
    async def _get_reminder_state(
        cls, 
        user_id: str, 
        plant_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the reminder state for a specific plant.
        
        Args:
            user_id: User's MongoDB ObjectId string.
            plant_id: Plant's MongoDB ObjectId string.
            
        Returns:
            Reminder state document or None if not found.
        """
        collection = cls._get_reminder_state_collection()
        return await collection.find_one({
            "user_id": user_id,
            "plant_id": plant_id
        })
    
    @classmethod
    async def _get_or_create_reminder_state(
        cls, 
        user_id: str, 
        plant_id: str
    ) -> Dict[str, Any]:
        """
        Get or create reminder state for a plant.
        
        Creates a new state document if one doesn't exist.
        
        Args:
            user_id: User's MongoDB ObjectId string.
            plant_id: Plant's MongoDB ObjectId string.
            
        Returns:
            Reminder state document.
        """
        collection = cls._get_reminder_state_collection()
        
        existing = await collection.find_one({
            "user_id": user_id,
            "plant_id": plant_id
        })
        
        if existing:
            return existing
        
        # Create new state
        new_state = {
            "user_id": user_id,
            "plant_id": plant_id,
            "consecutive_days": 0,
            "last_reminder_date": None,
            "last_action": None,
            "last_action_at": None,
            "paused_until": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        
        try:
            result = await collection.insert_one(new_state)
            new_state["_id"] = result.inserted_id
        except DuplicateKeyError:
            # Race condition - another request created it
            return await collection.find_one({
                "user_id": user_id,
                "plant_id": plant_id
            })
        
        return new_state
    
    @classmethod
    async def _update_reminder_state(
        cls,
        user_id: str,
        plant_id: str,
        action: str,
        reminder_day: int = None,
        snoozed_until: datetime = None
    ) -> Dict[str, Any]:
        """
        Update the reminder state after an action.
        
        Actions:
        - "sent": Reminder was sent (increment consecutive_days)
        - "watered": User marked plant as watered (reset state)
        - "snoozed": User snoozed the reminder
        - "ignored": Day passed without action (track for pause logic)
        
        Args:
            user_id: User's MongoDB ObjectId string.
            plant_id: Plant's MongoDB ObjectId string.
            action: Action that occurred.
            reminder_day: Current reminder day (for sent action).
            snoozed_until: When to resume reminders (for snooze action).
            
        Returns:
            Updated reminder state document.
        """
        collection = cls._get_reminder_state_collection()
        now = datetime.utcnow()
        date_key = now.strftime("%Y-%m-%d")
        
        update = {
            "$set": {
                "last_action": action,
                "last_action_at": now,
                "updated_at": now,
            }
        }
        
        if action == "sent":
            # Increment consecutive days
            update["$set"]["last_reminder_date"] = date_key
            if reminder_day:
                update["$set"]["consecutive_days"] = reminder_day
        
        elif action == "watered":
            # Reset state - plant was watered
            update["$set"]["consecutive_days"] = 0
            update["$set"]["paused_until"] = None
        
        elif action == "snoozed":
            # Set snooze time
            update["$set"]["snoozed_until"] = snoozed_until
        
        elif action == "ignored":
            # Track for pause logic (handled by should_pause_reminders)
            pass
        
        result = await collection.find_one_and_update(
            {"user_id": user_id, "plant_id": plant_id},
            update,
            upsert=True,
            return_document=True
        )
        
        return result
    
    @classmethod
    async def _should_pause_reminders(cls, reminder_state: Dict[str, Any]) -> bool:
        """
        Check if reminders should be paused for this plant.
        
        Reminders are paused when:
        - User has ignored reminders for max_days (default 5)
        - AND no explicit snooze was set
        
        Pausing respects user's silence and prevents notification fatigue.
        Reminders resume when user:
        - Opens the plant detail
        - Marks care as done
        - Explicitly re-enables reminders
        
        Args:
            reminder_state: Current reminder state document.
            
        Returns:
            True if reminders should be paused, False otherwise.
        """
        settings = cls._get_settings()
        max_days = settings.WATER_REMINDER_MAX_DAYS
        
        consecutive_days = reminder_state.get("consecutive_days", 0)
        last_action = reminder_state.get("last_action")
        paused_until = reminder_state.get("paused_until")
        
        # Check if explicitly paused
        if paused_until:
            if datetime.utcnow() < paused_until:
                return True
        
        # Check if max days reached without action
        if consecutive_days >= max_days:
            # Only pause if user hasn't snoozed (snooze = intentional)
            if last_action not in {"snoozed", "watered"}:
                return True
        
        return False
    
    # -------------------------------------------------------------------------
    # User Actions: Snooze, Watered, Dismiss
    # -------------------------------------------------------------------------
    
    @classmethod
    async def handle_action(
        cls,
        notification_id: str,
        user_id: str,
        action: str,
        plant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle user action on a water reminder notification.
        
        Actions:
        - "watered": Mark plant(s) as watered
        - "snooze_4h": Snooze for 4 hours
        - "snooze_tomorrow": Snooze until tomorrow morning
        - "dismiss": Dismiss notification
        
        Args:
            notification_id: Notification MongoDB ObjectId string.
            user_id: User's MongoDB ObjectId string.
            action: Action to perform.
            plant_id: Specific plant ID for batched notifications.
            
        Returns:
            Dict with action result.
        """
        notifications_collection = cls._get_notifications_collection()
        
        # Get the notification
        notification = await notifications_collection.find_one({
            "_id": ObjectId(notification_id),
            "user_id": user_id
        })
        
        if not notification:
            logger.warning(f"Notification {notification_id} not found for user {user_id}")
            return {"success": False, "error": "Notification not found"}
        
        if action == "watered":
            return await cls._handle_watered(notification, user_id, plant_id)
        elif action == "snooze_4h":
            return await cls._handle_snooze(notification, user_id, hours=4)
        elif action == "snooze_tomorrow":
            return await cls._handle_snooze_tomorrow(notification, user_id)
        elif action == "dismiss":
            return await cls._handle_dismiss(notification, user_id)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    
    @classmethod
    async def _handle_watered(
        cls,
        notification: Dict[str, Any],
        user_id: str,
        plant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle 'watered' action for a notification.
        
        Single plant: Marks the plant as watered and updates notification state.
        Batched: Marks specific plant or all plants if plant_id is None.
        
        Args:
            notification: Notification document.
            user_id: User's MongoDB ObjectId string.
            plant_id: Specific plant ID (for batched notifications).
            
        Returns:
            Dict with action result.
        """
        from app.plants.service import PlantService
        
        notifications_collection = cls._get_notifications_collection()
        now = datetime.utcnow()
        
        # Determine which plants to mark as watered
        plant_ids = notification.get("plant_ids", [])
        if not plant_ids and notification.get("plant_id"):
            plant_ids = [notification["plant_id"]]
        
        if plant_id:
            # Mark specific plant
            plants_to_mark = [plant_id] if plant_id in plant_ids else []
        else:
            # Mark all plants in notification
            plants_to_mark = plant_ids
        
        # Mark each plant as watered
        watered_plants = []
        for pid in plants_to_mark:
            try:
                await PlantService.mark_watered(pid, user_id)
                watered_plants.append(pid)
                
                # Reset reminder state for this plant
                await cls._update_reminder_state(user_id, pid, "watered")
            except Exception as e:
                logger.error(f"Failed to mark plant {pid} as watered: {e}")
        
        # Update notification state
        all_watered = set(watered_plants) >= set(plant_ids)
        new_state = NotificationState.ACTIONED.value if all_watered else notification.get("state")
        
        await notifications_collection.update_one(
            {"_id": notification["_id"]},
            {
                "$set": {
                    "state": new_state,
                    "actioned_at": now if all_watered else notification.get("actioned_at"),
                    "is_read": True,
                    "metadata.watered_plants": watered_plants,
                }
            }
        )
        
        # Get plant name for feedback message
        plant_name = "Your plant"
        if len(plants_to_mark) == 1:
            plant = await cls._get_plants_collection().find_one(
                {"_id": ObjectId(plants_to_mark[0])}
            )
            if plant:
                plant_name = plant.get("nickname") or plant.get("common_name") or "Your plant"
        
        feedback_message = (
            WaterReminderContent.action_confirmed_all() 
            if len(watered_plants) > 1 
            else WaterReminderContent.action_confirmed(plant_name)
        )
        
        return {
            "success": True,
            "watered_count": len(watered_plants),
            "all_watered": all_watered,
            "feedback_message": feedback_message
        }
    
    @classmethod
    async def _handle_snooze(
        cls,
        notification: Dict[str, Any],
        user_id: str,
        hours: int = 4
    ) -> Dict[str, Any]:
        """
        Handle snooze action for a notification.
        
        Creates a snoozed notification that will be delivered after
        the specified hours.
        
        Args:
            notification: Notification document.
            user_id: User's MongoDB ObjectId string.
            hours: Hours to snooze.
            
        Returns:
            Dict with action result.
        """
        notifications_collection = cls._get_notifications_collection()
        now = datetime.utcnow()
        snooze_until = now + timedelta(hours=hours)
        
        # Update notification state
        await notifications_collection.update_one(
            {"_id": notification["_id"]},
            {
                "$set": {
                    "state": NotificationState.SNOOZED.value,
                    "snoozed_until": snooze_until,
                    "is_read": True,
                }
            }
        )
        
        # Update reminder state for all plants in notification
        plant_ids = notification.get("plant_ids", [notification.get("plant_id")])
        for pid in plant_ids:
            if pid:
                await cls._update_reminder_state(
                    user_id, 
                    pid, 
                    "snoozed", 
                    snoozed_until=snooze_until
                )
        
        return {
            "success": True,
            "snoozed_until": snooze_until.isoformat(),
            "feedback_message": f"Reminder snoozed for {hours} hours"
        }
    
    @classmethod
    async def _handle_snooze_tomorrow(
        cls,
        notification: Dict[str, Any],
        user_id: str
    ) -> Dict[str, Any]:
        """
        Handle 'snooze until tomorrow morning' action.
        
        Calculates next 8 AM IST and schedules reminder for that time.
        If current time is after 5 PM, schedules for day after tomorrow.
        
        Args:
            notification: Notification document.
            user_id: User's MongoDB ObjectId string.
            
        Returns:
            Dict with action result.
        """
        settings = cls._get_settings()
        now_utc = datetime.utcnow()
        now_ist = now_utc.replace(tzinfo=pytz.UTC).astimezone(cls.IST)
        
        reminder_hour = settings.WATER_REMINDER_HOUR_IST
        
        # Calculate tomorrow 8 AM IST
        tomorrow = now_ist + timedelta(days=1)
        tomorrow_morning = tomorrow.replace(
            hour=reminder_hour, 
            minute=0, 
            second=0, 
            microsecond=0
        )
        
        # If it's after 5 PM, schedule for day after tomorrow
        # (to avoid very short snooze periods)
        if now_ist.hour >= 17:
            tomorrow_morning += timedelta(days=1)
        
        # Convert back to UTC for storage
        snooze_until = tomorrow_morning.astimezone(pytz.UTC).replace(tzinfo=None)
        
        notifications_collection = cls._get_notifications_collection()
        
        await notifications_collection.update_one(
            {"_id": notification["_id"]},
            {
                "$set": {
                    "state": NotificationState.SNOOZED.value,
                    "snoozed_until": snooze_until,
                    "is_read": True,
                }
            }
        )
        
        # Update reminder state for all plants
        plant_ids = notification.get("plant_ids", [notification.get("plant_id")])
        for pid in plant_ids:
            if pid:
                await cls._update_reminder_state(
                    user_id, 
                    pid, 
                    "snoozed", 
                    snoozed_until=snooze_until
                )
        
        return {
            "success": True,
            "snoozed_until": snooze_until.isoformat(),
            "feedback_message": "Reminder scheduled for tomorrow morning"
        }
    
    @classmethod
    async def _handle_dismiss(
        cls,
        notification: Dict[str, Any],
        user_id: str
    ) -> Dict[str, Any]:
        """
        Handle dismiss action for a notification.
        
        Marks the notification as dismissed without resetting reminder state.
        Reminder will continue the next day.
        
        Args:
            notification: Notification document.
            user_id: User's MongoDB ObjectId string.
            
        Returns:
            Dict with action result.
        """
        notifications_collection = cls._get_notifications_collection()
        
        await notifications_collection.update_one(
            {"_id": notification["_id"]},
            {
                "$set": {
                    "state": NotificationState.DISMISSED.value,
                    "is_read": True,
                }
            }
        )
        
        return {
            "success": True,
            "feedback_message": "Reminder dismissed"
        }
    
    # -------------------------------------------------------------------------
    # Snoozed Reminder Processing
    # -------------------------------------------------------------------------
    
    @classmethod
    async def process_snoozed_reminders(cls) -> Dict[str, int]:
        """
        Process snoozed reminders that are due.
        
        Called by Celery task periodically (e.g., every 30 minutes).
        Finds notifications with snoozed_until <= now and sends push.
        
        Returns:
            Dict with processing stats.
        """
        notifications_collection = cls._get_notifications_collection()
        now = datetime.utcnow()
        
        stats = {
            "processed": 0,
            "sent": 0,
            "errors": 0
        }
        
        cursor = notifications_collection.find({
            "state": NotificationState.SNOOZED.value,
            "snoozed_until": {"$lte": now}
        })
        
        async for notification in cursor:
            stats["processed"] += 1
            try:
                # Send push notification
                await cls._send_push_for_notification(notification)
                
                # Update state to SENT (ready for delivery)
                await notifications_collection.update_one(
                    {"_id": notification["_id"]},
                    {
                        "$set": {
                            "state": NotificationState.SENT.value,
                            "snoozed_until": None,
                            "is_read": False,  # Mark unread again
                        }
                    }
                )
                stats["sent"] += 1
            except Exception as e:
                logger.error(f"Failed to process snoozed notification {notification['_id']}: {e}")
                stats["errors"] += 1
        
        if stats["sent"] > 0:
            logger.info(f"Processed snoozed reminders: {stats}")
        
        return stats
    
    @classmethod
    async def _send_push_for_notification(cls, notification: Dict[str, Any]) -> bool:
        """
        Send a push notification to the user's device.
        
        Integrates with AWS SNS for actual push delivery.
        
        Args:
            notification: Notification document to send.
            
        Returns:
            True if push was sent successfully, False otherwise.
        """
        # Import here to avoid circular imports
        from app.notifications.push_service import PushNotificationService
        
        try:
            await PushNotificationService.send_push(
                user_id=notification["user_id"],
                title=notification["title"],
                body=notification["message"],
                data={
                    "notification_id": str(notification["_id"]),
                    "notification_type": notification["notification_type"],
                    "plant_id": notification.get("plant_id"),
                    "action_url": notification.get("action_url"),
                }
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # Resume Reminders (when user opens plant or re-enables)
    # -------------------------------------------------------------------------
    
    @classmethod
    async def resume_reminders_for_plant(
        cls, 
        user_id: str, 
        plant_id: str
    ) -> bool:
        """
        Resume paused reminders for a plant.
        
        Called when:
        - User opens plant detail page
        - User explicitly re-enables reminders
        
        Args:
            user_id: User's MongoDB ObjectId string.
            plant_id: Plant's MongoDB ObjectId string.
            
        Returns:
            True if reminders were resumed, False if not paused.
        """
        collection = cls._get_reminder_state_collection()
        
        result = await collection.update_one(
            {
                "user_id": user_id,
                "plant_id": plant_id,
                "consecutive_days": {"$gte": get_settings().WATER_REMINDER_MAX_DAYS}
            },
            {
                "$set": {
                    "consecutive_days": 0,
                    "paused_until": None,
                    "last_action": "resumed",
                    "last_action_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"Resumed reminders for user {user_id} plant {plant_id}")
            return True
        
        return False
