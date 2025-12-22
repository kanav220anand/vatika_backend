"""Achievement API routes."""

from typing import List
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.achievements.models import AchievementsListResponse
from app.achievements.service import AchievementService


router = APIRouter(prefix="/achievements", tags=["Achievements"])


@router.get("", response_model=AchievementsListResponse)
async def get_achievements(
    current_user: dict = Depends(get_current_user)
):
    """
    Get all achievements with user's unlock status from database.
    Only shows achievements as unlocked if they exist in user_achievements.
    Use POST /achievements/check to unlock earned achievements.
    """
    # Only fetch from DB - no auto-unlock
    return await AchievementService.get_all_achievements(current_user["id"])



@router.post("/check")
async def check_achievements(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Manually check and unlock any earned achievements.
    Returns list of newly unlocked achievements.
    """
    newly_unlocked = await AchievementService.check_and_unlock_achievements(
        current_user["id"]
    )
    
    return {
        "newly_unlocked": newly_unlocked,
        "count": len(newly_unlocked)
    }


@router.get("/stats")
async def get_user_stats(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Get user's current stats for achievement progress."""
    stats = await AchievementService.get_user_stats(current_user["id"])
    
    return {
        "plant_count": stats.plant_count,
        "healthy_plants": stats.healthy_plants,
        "total_waterings": stats.total_waterings,
        "max_streak": stats.max_streak,
        "unique_species": stats.unique_species,
        "plants_revived": stats.plants_revived,
    }


@router.get("/definitions")
async def get_achievement_definitions() -> dict:
    """Get all achievement definitions (public endpoint for reference)."""
    achievements = await AchievementService.get_all_achievement_definitions()
    
    return {
        "achievements": [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "description": a.get("description"),
                "icon": a.get("icon"),
                "category": a.get("category"),
                "tier": a.get("tier"),
                "points": a.get("points"),
                "condition_type": a.get("condition_type"),
                "condition_value": a.get("condition_value"),
            }
            for a in achievements
        ],
        "total": len(achievements)
    }


@router.post("/{achievement_id}/unlock")
async def unlock_achievement(
    achievement_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Manually unlock a specific achievement for the user.
    Used for special achievements like 'early_adopter' during onboarding.
    """
    was_new = await AchievementService.unlock_achievement(
        current_user["id"],
        achievement_id
    )
    
    if was_new:
        # Get achievement details
        achievements = await AchievementService.get_all_achievement_definitions()
        achievement = next((a for a in achievements if a.get("id") == achievement_id), None)
        
        return {
            "success": True,
            "newly_unlocked": True,
            "achievement": {
                "id": achievement_id,
                "name": achievement.get("name") if achievement else achievement_id,
                "icon": achievement.get("icon") if achievement else "🏆",
                "points": achievement.get("points") if achievement else 0,
            } if achievement else None
        }
    
    return {
        "success": True,
        "newly_unlocked": False,
        "message": "Achievement already unlocked"
    }
