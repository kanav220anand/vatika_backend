"""Gamification API endpoints."""

from typing import List
from fastapi import APIRouter
from app.gamification.service import GamificationService
from app.gamification.models import LevelResponse

router = APIRouter(prefix="/api/levels", tags=["Gamification"])


@router.get("", response_model=List[LevelResponse])
async def get_all_levels():
    """
    Get all available user levels.
    This is a public endpoint (no auth required) since levels are static data.
    """
    return await GamificationService.get_all_levels()
