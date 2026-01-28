"""API routes for recommended plants."""

from typing import Optional, Literal
from fastapi import APIRouter, Query
from app.recommended_plants.service import RecommendedPlantsService
from app.recommended_plants.schemas import RecommendedPlantsListResponse, RecommendedPlantResponse

router = APIRouter(prefix="/recommended-plants", tags=["Recommended Plants"])


@router.get("", response_model=RecommendedPlantsListResponse)
async def get_recommended_plants(
    skip: int = Query(0, ge=0, description="Number of plants to skip"),
    limit: int = Query(10, ge=1, le=50, description="Max plants to return"),
    beginner_only: bool = Query(False, description="Only show beginner-friendly plants"),
    difficulty: Optional[Literal["easy", "medium", "hard"]] = Query(None, description="Filter by difficulty level"),
    light_needs: Optional[Literal["low", "medium", "bright"]] = Query(None, description="Filter by light requirements"),
    sort_by: Optional[Literal["name", "difficulty", "popularity"]] = Query(None, description="Sort field"),
    sort_order: Optional[Literal["asc", "desc"]] = Query("asc", description="Sort order"),
):
    """
    Get paginated list of recommended plants with filters and sorting.
    
    - **skip**: Offset for pagination (default: 0)
    - **limit**: Max items per page (default: 10, max: 50)
    - **beginner_only**: Filter for beginner-friendly plants only
    - **difficulty**: Filter by difficulty (easy, medium, hard)
    - **light_needs**: Filter by light requirements (low, medium, bright)
    - **sort_by**: Sort by field (name, difficulty, popularity)
    - **sort_order**: Sort order (asc, desc)
    
    Response includes `has_more` flag to indicate if more plants exist.
    """
    plants, total, has_more = await RecommendedPlantsService.get_plants(
        skip=skip,
        limit=limit,
        beginner_only=beginner_only,
        difficulty=difficulty,
        light_needs=light_needs,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    return RecommendedPlantsListResponse(
        plants=plants,
        total=total,
        has_more=has_more
    )


@router.get("/{plant_id}", response_model=RecommendedPlantResponse)
async def get_recommended_plant(plant_id: str):
    """
    Get a single recommended plant by ID.
    """
    plant = await RecommendedPlantsService.get_plant_by_id(plant_id)
    return plant
