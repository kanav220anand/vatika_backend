"""Pydantic schemas for recommended plants."""

from pydantic import BaseModel
from typing import Optional


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


class RecommendedPlantResponse(RecommendedPlantBase):
    """Response schema for recommended plant."""
    
    class Config:
        from_attributes = True


class RecommendedPlantsListResponse(BaseModel):
    """Paginated response for recommended plants list."""
    plants: list[RecommendedPlantResponse]
    total: int
    has_more: bool
