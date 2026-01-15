"""Achievement models and definitions."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class AchievementCategory(str, Enum):
    """Categories of achievements."""
    COLLECTION = "collection"
    WATERING = "watering"
    HEALTH = "health"
    KNOWLEDGE = "knowledge"
    LOYALTY = "loyalty"


class AchievementTier(str, Enum):
    """Achievement difficulty tiers."""
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class UserAchievement(BaseModel):
    """A user's unlocked achievement (stored in user_achievements collection)."""
    id: str
    user_id: str
    achievement_id: str
    unlocked_at: datetime
    

class AchievementResponse(BaseModel):
    """Response for a single achievement."""
    id: str
    name: str
    description: str
    icon: str
    category: str
    tier: str
    points: int
    unlocked: bool = False
    unlocked_at: Optional[datetime] = None
    progress: float = 0.0  # 0-1 for progress bar
    condition_type: Optional[str] = None
    condition_value: Optional[int] = None


class AchievementsListResponse(BaseModel):
    """Response containing all achievements and user progress."""
    achievements: List[AchievementResponse]
    total_points: int
    unlocked_count: int
    total_count: int


class UserStats(BaseModel):
    """User statistics for achievement calculation."""
    plant_count: int = 0
    healthy_plants: int = 0
    total_waterings: int = 0
    max_streak: int = 0
    unique_species: int = 0
    water_actions_count: int = 0
    water_on_time_count: int = 0
    water_early_count: int = 0
    water_late_count: int = 0
    plants_revived: int = 0
    all_healthy_days: int = 0


class AchievementDefinition(BaseModel):
    """Schema for achievement definitions stored in database."""
    id: str
    name: str
    description: str
    icon: str
    category: str
    tier: str
    condition_type: str  # plant_count, total_waterings, max_streak, etc.
    condition_value: int
    points: int = 10
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
