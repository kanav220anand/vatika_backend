"""Pydantic schemas for user plant wishlist."""

from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class WishlistItemBase(BaseModel):
    """Base schema for wishlist item."""
    plant_id: str
    common_name: str
    scientific_name: str
    image_url: Optional[str] = None
    difficulty: str
    price_range: Optional[str] = None


class WishlistItemCreate(BaseModel):
    """Schema for adding a plant to wishlist."""
    plant_id: str
    common_name: str
    scientific_name: str
    image_url: Optional[str] = None
    difficulty: str
    price_range: Optional[str] = None


class WishlistItemResponse(WishlistItemBase):
    """Response schema for a single wishlist item."""
    added_at: datetime
    
    class Config:
        from_attributes = True


class WishlistResponse(BaseModel):
    """Response schema for user's full wishlist."""
    items: list[WishlistItemResponse]
    count: int


class WishlistToggleResponse(BaseModel):
    """Response for toggle operation."""
    wishlisted: bool
    message: str
