"""Achievements module for gamification."""

from fastapi import APIRouter

router = APIRouter(prefix="/achievements", tags=["Achievements"])

from app.achievements.views import router as achievements_router

__all__ = ["achievements_router"]
