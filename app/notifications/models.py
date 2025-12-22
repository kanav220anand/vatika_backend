"""Notification models and schemas."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class NotificationType(str, Enum):
    """Types of notifications."""
    HEALTH_ALERT = "health_alert"
    WATER_REMINDER = "water_reminder"
    ACTION_REQUIRED = "action_required"
    WEATHER_ALERT = "weather_alert"


class NotificationPriority(str, Enum):
    """Notification priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NotificationCreate(BaseModel):
    """Schema for creating a notification."""
    user_id: str
    notification_type: NotificationType
    priority: NotificationPriority = NotificationPriority.MEDIUM
    title: str
    message: str
    plant_id: Optional[str] = None  # Reference to user's plant (MongoDB ObjectId)
    action_url: Optional[str] = None  # Deep link to relevant page


class NotificationResponse(BaseModel):
    """Response schema for a notification."""
    id: str
    user_id: str
    notification_type: str
    priority: str
    title: str
    message: str
    plant_id: Optional[str] = None
    plant_name: Optional[str] = None
    action_url: Optional[str] = None
    is_read: bool = False
    created_at: datetime


class NotificationListResponse(BaseModel):
    """Response with list of notifications and counts."""
    notifications: List[NotificationResponse]
    total_count: int
    unread_count: int
