"""
Notification Models and Schemas

This module defines all Pydantic models for the notification system.
Includes support for:
- Multiple notification types (water reminders, health alerts, etc.)
- State machine for notification lifecycle tracking
- Batched notifications (multiple plants in one notification)
- Snooze functionality with scheduled re-delivery
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class NotificationType(str, Enum):
    """
    Types of notifications supported by the system.
    
    Each type has different triggering logic and content templates.
    """
    HEALTH_ALERT = "health_alert"           # Plant health issues detected
    WATER_REMINDER = "water_reminder"       # Daily watering reminders
    WATER_CHECK = "water_check"             # Soil check for unknown history
    WATER_CHECK_SUMMARY = "water_check_summary"  # Daily summary for water checks
    ACTION_REQUIRED = "action_required"     # Urgent plant care needed
    WEATHER_ALERT = "weather_alert"         # Weather-based care tips
    STREAK_MILESTONE = "streak_milestone"   # Watering streak achievements
    ACHIEVEMENT_UNLOCKED = "achievement_unlocked"  # Gamification rewards


class NotificationPriority(str, Enum):
    """
    Notification priority levels.
    
    Affects visual styling and potentially notification ordering.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NotificationState(str, Enum):
    """
    Notification lifecycle states.
    
    Tracks the user's interaction with each notification:
    - sent: Notification created and stored in database
    - delivered: Push notification delivered to device (if applicable)
    - opened: User tapped/opened the notification
    - actioned: User completed the suggested action (e.g., marked watered)
    - snoozed: User chose to be reminded later
    - dismissed: User dismissed without action
    - expired: Max reminder days reached without action
    """
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    ACTIONED = "actioned"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class NotificationCreate(BaseModel):
    """
    Schema for creating a notification.
    
    Used internally when generating notifications from business logic.
    Supports both single-plant and batched (multi-plant) notifications.
    """
    user_id: str
    notification_type: NotificationType
    priority: NotificationPriority = NotificationPriority.MEDIUM
    title: str
    message: str
    
    # Single plant reference (legacy, still supported)
    plant_id: Optional[str] = None
    
    # Multiple plants support (for batched notifications)
    plant_ids: List[str] = Field(
        default_factory=list,
        description="List of plant IDs included in this notification (for batched reminders)."
    )
    primary_plant_id: Optional[str] = Field(
        default=None,
        description="The main plant shown in notification (most overdue for water reminders)."
    )
    
    # Image for notification (plant image or Vatisha logo)
    image_url: Optional[str] = Field(
        default=None,
        description="Image URL to display with notification (plant photo or app logo)."
    )
    
    action_url: Optional[str] = None  # Deep link to relevant page
    
    dedupe_key: Optional[str] = Field(
        default=None,
        description="Optional idempotency key to prevent duplicate notifications (server-side).",
    )
    
    # State machine fields
    state: NotificationState = Field(
        default=NotificationState.SENT,
        description="Current lifecycle state of the notification."
    )
    reminder_day: int = Field(
        default=1,
        description="Which day of the reminder sequence (1-5 for water reminders)."
    )
    snoozed_until: Optional[datetime] = Field(
        default=None,
        description="If snoozed, when to send the next reminder."
    )
    
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured payload for in-app rendering (kept small).",
    )


class NotificationResponse(BaseModel):
    """
    Response schema for a notification.
    
    Returned by API endpoints to the frontend.
    Includes computed fields like plant_name from joins.
    """
    id: str
    user_id: str
    notification_type: str
    priority: str
    title: str
    message: str
    
    # Image and icon
    image_url: Optional[str] = Field(
        default=None,
        description="Image URL for the notification (plant photo or app logo)."
    )
    icon_url: Optional[str] = Field(
        default=None,
        description="Public URL for notification icon (type-specific icon).",
    )
    
    # Plant references
    plant_id: Optional[str] = None
    plant_name: Optional[str] = None
    plant_ids: List[str] = Field(default_factory=list)
    primary_plant_id: Optional[str] = None
    
    action_url: Optional[str] = None
    
    # State machine
    state: str = Field(default="sent")
    is_read: bool = False  # Legacy field, derived from state
    reminder_day: int = Field(default=1)
    snoozed_until: Optional[datetime] = None
    actioned_at: Optional[datetime] = Field(
        default=None,
        description="When the user completed the action (e.g., marked watered)."
    )
    
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class NotificationListResponse(BaseModel):
    """Response with list of notifications and counts."""
    notifications: List[NotificationResponse]
    total_count: int
    unread_count: int


class NotificationActionRequest(BaseModel):
    """
    Request schema for taking action on a notification.
    
    Used when user taps 'Watered', 'Snooze', etc.
    """
    action: str = Field(
        ...,
        description="Action to take: 'watered', 'snooze_4h', 'snooze_tomorrow', 'dismiss'"
    )
    plant_id: Optional[str] = Field(
        default=None,
        description="Specific plant ID if marking single plant in batched notification."
    )


class SnoozeOption(BaseModel):
    """Schema for a snooze option presented to user."""
    id: str  # e.g., "snooze_4h", "snooze_tomorrow"
    label: str  # e.g., "In 4 hours", "Tomorrow morning"
    duration_hours: Optional[int] = None  # For time-based snooze
