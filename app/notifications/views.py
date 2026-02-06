"""Notifications API routes."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, status, Body

from app.core.dependencies import get_current_user
from app.core.exceptions import AppException
from app.notifications.models import (
    NotificationResponse,
    NotificationListResponse,
    NotificationActionRequest,
    SnoozeOption,
)
from app.notifications.service import NotificationService
from app.notifications.water_reminder_service import WaterReminderService
from app.notifications.content import WaterReminderContent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    limit: int = Query(default=50, le=100),
    include_read: bool = Query(default=True),
    current_user: dict = Depends(get_current_user)
):
    """
    Get user's notifications.
    
    Returns notifications sorted by unread first, then by date.
    Note: This endpoint must not perform side effects (e.g. generating reminders).
    """
    user_id = current_user["id"]

    # Get all notifications
    notifications, total, unread = await NotificationService.get_user_notifications(
        user_id=user_id,
        limit=limit,
        include_read=include_read
    )
    
    return NotificationListResponse(
        notifications=notifications,
        total_count=total,
        unread_count=unread
    )

@router.get("/unread-count")
async def get_unread_count(current_user: dict = Depends(get_current_user)):
    """
    Get unread notification count (cheap endpoint for badge polling).

    Sanity checks:
    - returns 0 when no notifications exist
    - increments when an unread notification is created
    - decreases when notifications are marked as read
    """
    unread = await NotificationService.get_unread_count(current_user["id"])
    return {"unread_count": unread}


@router.get("/count")
async def get_notification_count(
    current_user: dict = Depends(get_current_user)
):
    """Deprecated: use /notifications/unread-count."""
    unread = await NotificationService.get_unread_count(current_user["id"])
    return {"unread_count": unread}


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Mark a specific notification as read."""
    try:
        return await NotificationService.mark_as_read(
            notification_id=notification_id,
            user_id=current_user["id"]
        )
    except Exception as e:
        raise AppException(f"Failed to mark notification as read: {str(e)}")


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read_patch(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """PATCH alias for marking a notification as read (frontend compatibility)."""
    return await mark_notification_read(notification_id, current_user)


@router.post("/read-all")
async def mark_all_read(
    current_user: dict = Depends(get_current_user)
):
    """Mark all notifications as read."""
    count = await NotificationService.mark_all_as_read(current_user["id"])
    return {"marked_read": count}


@router.patch("/read-all")
async def mark_all_read_patch(
    current_user: dict = Depends(get_current_user)
):
    """PATCH alias for marking all notifications as read (frontend compatibility)."""
    return await mark_all_read(current_user)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete/dismiss a notification."""
    try:
        await NotificationService.delete_notification(
            notification_id=notification_id,
            user_id=current_user["id"]
        )
    except Exception as e:
        raise AppException(f"Failed to delete notification: {str(e)}")


# =============================================================================
# Water Reminder Actions
# =============================================================================

@router.post("/{notification_id}/action")
async def perform_notification_action(
    notification_id: str,
    request: NotificationActionRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Perform an action on a notification.
    
    Actions:
    - "watered": Mark plant(s) as watered
    - "snooze_4h": Snooze for 4 hours
    - "snooze_tomorrow": Snooze until tomorrow morning
    - "dismiss": Dismiss notification
    
    For batched notifications, optionally specify plant_id to action
    a specific plant only.
    """
    user_id = current_user["id"]
    
    try:
        result = await WaterReminderService.handle_action(
            notification_id=notification_id,
            user_id=user_id,
            action=request.action,
            plant_id=request.plant_id
        )
        
        if not result.get("success"):
            raise AppException(result.get("error", "Action failed"))
        
        return result
    
    except Exception as e:
        logger.error(f"Failed to perform action on notification {notification_id}: {e}")
        raise AppException(f"Failed to perform action: {str(e)}")


@router.post("/{notification_id}/watered")
async def mark_notification_watered(
    notification_id: str,
    plant_id: Optional[str] = Body(default=None, embed=True),
    current_user: dict = Depends(get_current_user)
):
    """
    Mark plant(s) from a water reminder as watered.
    
    For single plant notifications: marks that plant as watered.
    For batched notifications: specify plant_id to mark specific plant,
    or omit to mark all plants.
    """
    user_id = current_user["id"]
    
    try:
        result = await WaterReminderService.handle_action(
            notification_id=notification_id,
            user_id=user_id,
            action="watered",
            plant_id=plant_id
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Failed to mark notification {notification_id} as watered: {e}")
        raise AppException(f"Failed to mark as watered: {str(e)}")


@router.post("/{notification_id}/snooze")
async def snooze_notification(
    notification_id: str,
    option: str = Body(embed=True, description="Snooze option: '4h' or 'tomorrow'"),
    current_user: dict = Depends(get_current_user)
):
    """
    Snooze a notification for later reminder.
    
    Options:
    - "4h": Remind in 4 hours
    - "tomorrow": Remind tomorrow morning at 8 AM
    """
    user_id = current_user["id"]
    
    action = "snooze_4h" if option == "4h" else "snooze_tomorrow"
    
    try:
        result = await WaterReminderService.handle_action(
            notification_id=notification_id,
            user_id=user_id,
            action=action
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Failed to snooze notification {notification_id}: {e}")
        raise AppException(f"Failed to snooze: {str(e)}")


@router.get("/snooze-options")
async def get_snooze_options(
    current_user: dict = Depends(get_current_user)
):
    """
    Get available snooze options for water reminders.
    
    Returns predefined snooze choices.
    """
    options = WaterReminderContent.get_snooze_options()
    return {
        "options": [
            SnoozeOption(id=opt["id"], label=opt["label"], duration_hours=opt.get("hours"))
            for opt in options
        ]
    }


# =============================================================================
# Device Registration for Push Notifications
# =============================================================================

@router.post("/device/register")
async def register_device(
    device_token: str = Body(..., embed=True),
    platform: str = Body(..., embed=True, description="'ios' or 'android'"),
    device_id: Optional[str] = Body(default=None, embed=True),
    current_user: dict = Depends(get_current_user)
):
    """
    Register a device for push notifications.
    
    Must be called when:
    - User first enables notifications
    - App obtains a new push token
    """
    from app.notifications.push_service import PushNotificationService
    
    user_id = current_user["id"]
    
    if platform not in ("ios", "android"):
        raise AppException("Platform must be 'ios' or 'android'")
    
    try:
        result = await PushNotificationService.register_device(
            user_id=user_id,
            device_token=device_token,
            platform=platform,
            device_id=device_id
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Failed to register device for user {user_id}: {e}")
        raise AppException(f"Failed to register device: {str(e)}")


@router.delete("/device/unregister")
async def unregister_device(
    device_token: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    """
    Unregister a device from push notifications.
    
    Should be called when:
    - User disables notifications
    - User logs out
    """
    from app.notifications.push_service import PushNotificationService
    
    user_id = current_user["id"]
    
    try:
        success = await PushNotificationService.unregister_device(
            user_id=user_id,
            device_token=device_token
        )
        
        return {"success": success}
    
    except Exception as e:
        logger.error(f"Failed to unregister device for user {user_id}: {e}")
        raise AppException(f"Failed to unregister device: {str(e)}")


# =============================================================================
# Debug Endpoints (only available in DEBUG mode)
# =============================================================================

@router.post("/debug/trigger-water-reminders")
async def debug_trigger_water_reminders(
    current_user: dict = Depends(get_current_user)
):
    """
    [DEBUG] Trigger water reminder generation for the current user.
    
    This bypasses the Celery scheduler and generates reminders immediately.
    Useful for testing the notification flow.
    
    Only available when DEBUG=True.
    """
    from app.core.config import get_settings
    
    settings = get_settings()
    if not settings.DEBUG:
        raise AppException("Debug endpoints are only available in DEBUG mode", status_code=403)
    
    user_id = current_user["id"]
    
    try:
        result = await WaterReminderService.generate_user_water_reminder(user_id)
        
        if result:
            return {
                "success": True,
                "message": "Water reminder created",
                "notification_id": result.get("notification_id"),
                "plant_count": result.get("plant_count"),
                "primary_plant": result.get("primary_plant"),
                "reminder_day": result.get("reminder_day"),
            }
        else:
            return {
                "success": False,
                "message": "No plants need watering today (or reminder already sent)",
            }
    
    except Exception as e:
        logger.error(f"Debug trigger failed for user {user_id}: {e}")
        raise AppException(f"Failed to trigger reminders: {str(e)}")


@router.post("/debug/make-plant-overdue")
async def debug_make_plant_overdue(
    plant_id: str = Body(..., embed=True),
    days_ago: int = Body(default=7, embed=True),
    current_user: dict = Depends(get_current_user)
):
    """
    [DEBUG] Update a plant's last_watered to make it overdue.
    
    This sets last_watered to `days_ago` days in the past, which should
    trigger a water reminder when the task runs.
    
    Only available when DEBUG=True.
    
    Args:
        plant_id: The plant to update
        days_ago: How many days ago to set last_watered (default 7)
    """
    from datetime import datetime, timedelta
    from bson import ObjectId
    from app.core.config import get_settings
    from app.core.database import Database
    
    settings = get_settings()
    if not settings.DEBUG:
        raise AppException("Debug endpoints are only available in DEBUG mode", status_code=403)
    
    user_id = current_user["id"]
    
    try:
        plants_collection = Database.get_collection("plants")
        
        # Verify plant belongs to user
        plant = await plants_collection.find_one({
            "_id": ObjectId(plant_id),
            "user_id": user_id
        })
        
        if not plant:
            raise AppException("Plant not found or doesn't belong to you", status_code=404)
        
        # Update last_watered
        new_last_watered = datetime.utcnow() - timedelta(days=days_ago)
        
        await plants_collection.update_one(
            {"_id": ObjectId(plant_id)},
            {
                "$set": {
                    "last_watered": new_last_watered,
                    "last_watered_source": "user_exact",
                }
            }
        )
        
        return {
            "success": True,
            "plant_id": plant_id,
            "plant_name": plant.get("nickname") or plant.get("common_name"),
            "last_watered": new_last_watered.isoformat(),
            "message": f"Plant last_watered set to {days_ago} days ago. Run trigger-water-reminders to generate notification.",
        }
    
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Debug make-overdue failed: {e}")
        raise AppException(f"Failed to update plant: {str(e)}")


@router.get("/debug/check-plants-needing-water")
async def debug_check_plants_needing_water(
    current_user: dict = Depends(get_current_user)
):
    """
    [DEBUG] Check which plants need watering for the current user.
    
    Returns a list of plants with their watering status.
    Useful for verifying the watering engine logic.
    
    Only available when DEBUG=True.
    """
    from datetime import datetime
    from app.core.config import get_settings
    from app.core.database import Database
    from app.plants.watering_engine import compute_watering_recommendation
    
    settings = get_settings()
    if not settings.DEBUG:
        raise AppException("Debug endpoints are only available in DEBUG mode", status_code=403)
    
    user_id = current_user["id"]
    
    try:
        plants_collection = Database.get_collection("plants")
        now = datetime.utcnow()
        
        plants_status = []
        cursor = plants_collection.find({"user_id": user_id})
        
        async for plant in cursor:
            rec = compute_watering_recommendation(plant, now=now)
            
            plants_status.append({
                "plant_id": str(plant["_id"]),
                "name": plant.get("nickname") or plant.get("common_name"),
                "last_watered": plant.get("last_watered").isoformat() if plant.get("last_watered") else None,
                "next_water_date": rec.next_water_date.isoformat() if rec.next_water_date else None,
                "urgency": rec.urgency,
                "days_until_due": rec.days_until_due,
                "recommended_action": rec.recommended_action,
                "reminders_enabled": plant.get("reminders_enabled", True),
            })
        
        # Sort by urgency
        urgency_order = {"overdue": 0, "due_today": 1, "upcoming": 2}
        plants_status.sort(key=lambda p: (urgency_order.get(p["urgency"], 3), p.get("days_until_due") or 999))
        
        needs_water = [p for p in plants_status if p["urgency"] in ("due_today", "overdue")]
        
        return {
            "total_plants": len(plants_status),
            "plants_needing_water": len(needs_water),
            "plants": plants_status,
        }
    
    except Exception as e:
        logger.error(f"Debug check failed: {e}")
        raise AppException(f"Failed to check plants: {str(e)}")
