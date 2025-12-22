"""Gamification models - Level definitions and responses."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class LevelDefinition(BaseModel):
    """MongoDB document schema for user_levels collection."""
    level: int
    title: str
    icon: str
    min_points: int
    max_points: Optional[int]  # None for max level
    description: str
    color: str
    badge_image_url: Optional[str] = None
    perks: List[str] = []
    sort_order: int
    is_active: bool = True
    created_at: datetime = datetime.utcnow()
    updated_at: datetime = datetime.utcnow()


class LevelResponse(BaseModel):
    """API response for a single level."""
    level: int
    title: str
    icon: str
    min_points: int
    max_points: Optional[int]
    description: str
    color: str
    badge_image_url: Optional[str] = None
    perks: List[str] = []


class UserLevelResponse(BaseModel):
    """Response when getting a user's current level info."""
    level: int
    title: str
    icon: str
    color: str
    current_points: int
    points_to_next_level: Optional[int]  # None if at max level
    progress_percent: float  # 0-100
    next_level_title: Optional[str] = None
