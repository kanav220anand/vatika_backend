"""Pydantic schemas for recommended plants."""

from pydantic import BaseModel
from typing import Optional, Literal


class RecommendedPlantBase(BaseModel):
    """Base schema for recommended plant."""
    plant_id: str
    common_name: str
    scientific_name: str
    image_url: str
    difficulty: str  # "easy", "medium", "hard"
    light_needs: str  # "low", "medium", "bright"
    water_frequency: str
    description: str
    is_beginner_friendly: bool = True
    order: int = 0
    # New fields
    success_rate: Optional[int] = None
    quick_benefit: Optional[str] = None
    price_range: Optional[str] = None
    google_search_term: Optional[str] = None
    care_tip: Optional[str] = None
    growth_speed: Optional[str] = None  # "slow", "medium", "fast"


class RecommendedPlantResponse(RecommendedPlantBase):
    """Response schema for recommended plant."""
    
    class Config:
        from_attributes = True


class RecommendedPlantsListResponse(BaseModel):
    """Paginated response for recommended plants list."""
    plants: list[RecommendedPlantResponse]
    total: int
    has_more: bool
