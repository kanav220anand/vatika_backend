"""Notifications API routes."""

from typing import Optional
from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_current_user
from app.core.exceptions import AppException
from app.notifications.models import (
    NotificationResponse,
    NotificationListResponse,
)
from app.notifications.service import NotificationService

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
    Also triggers check for watering reminders.
    """
    user_id = current_user["id"]
    
    # Check for new watering reminders
    await NotificationService.check_watering_reminders(user_id)
    
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


@router.get("/count")
async def get_notification_count(
    current_user: dict = Depends(get_current_user)
):
    """Get unread notification count (lightweight endpoint for badge)."""
    _, _, unread = await NotificationService.get_user_notifications(
        user_id=current_user["id"],
        limit=1,
        include_read=False
    )
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


@router.post("/read-all")
async def mark_all_read(
    current_user: dict = Depends(get_current_user)
):
    """Mark all notifications as read."""
    count = await NotificationService.mark_all_as_read(current_user["id"])
    return {"marked_read": count}


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
