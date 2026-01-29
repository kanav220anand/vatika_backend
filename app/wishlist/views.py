"""API routes for user plant wishlist."""

from fastapi import APIRouter, Depends, HTTPException, status
from app.core.dependencies import get_current_user
from app.wishlist.service import WishlistService
from app.wishlist.schemas import (
    WishlistItemCreate,
    WishlistItemResponse,
    WishlistResponse,
    WishlistToggleResponse,
)

router = APIRouter(prefix="/user-plant-wishlist", tags=["Wishlist"])


@router.get("", response_model=WishlistResponse)
async def get_wishlist(current_user: dict = Depends(get_current_user)):
    """
    Get the current user's plant wishlist.
    
    Returns all wishlisted plants sorted by most recently added.
    """
    items = await WishlistService.get_user_wishlist(current_user["id"])
    return WishlistResponse(items=items, count=len(items))


@router.get("/ids", response_model=list[str])
async def get_wishlist_ids(current_user: dict = Depends(get_current_user)):
    """
    Get just the plant IDs in the user's wishlist.
    
    Useful for quick client-side lookup without fetching full data.
    """
    plant_ids = await WishlistService.get_wishlist_plant_ids(current_user["id"])
    return list(plant_ids)


@router.post("", response_model=WishlistItemResponse, status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    item: WishlistItemCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Add a plant to the user's wishlist.
    
    If the plant is already in the wishlist, returns the existing item.
    """
    wishlist_item = await WishlistService.add_to_wishlist(
        user_id=current_user["id"],
        plant_data=item.model_dump()
    )
    return wishlist_item


@router.post("/toggle", response_model=WishlistToggleResponse)
async def toggle_wishlist(
    item: WishlistItemCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Toggle a plant in/out of the user's wishlist.
    
    If the plant is in the wishlist, it will be removed.
    If the plant is not in the wishlist, it will be added.
    """
    is_wishlisted, message = await WishlistService.toggle_wishlist(
        user_id=current_user["id"],
        plant_data=item.model_dump()
    )
    return WishlistToggleResponse(wishlisted=is_wishlisted, message=message)


@router.delete("/{plant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_wishlist(
    plant_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Remove a plant from the user's wishlist.
    
    Returns 204 No Content on success, 404 if plant was not in wishlist.
    """
    removed = await WishlistService.remove_from_wishlist(
        user_id=current_user["id"],
        plant_id=plant_id
    )
    
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found in wishlist"
        )


@router.get("/{plant_id}/check", response_model=bool)
async def check_wishlisted(
    plant_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Check if a specific plant is in the user's wishlist.
    
    Returns true if wishlisted, false otherwise.
    """
    return await WishlistService.is_wishlisted(current_user["id"], plant_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_wishlist(current_user: dict = Depends(get_current_user)):
    """
    Clear all items from the user's wishlist.
    """
    await WishlistService.clear_user_wishlist(current_user["id"])
