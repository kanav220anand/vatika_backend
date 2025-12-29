"""API routes for recommended plants."""

from fastapi import APIRouter, Query
from app.recommended_plants.service import RecommendedPlantsService
from app.recommended_plants.schemas import RecommendedPlantsListResponse

router = APIRouter(prefix="/recommended-plants", tags=["Recommended Plants"])


@router.get("", response_model=RecommendedPlantsListResponse)
async def get_recommended_plants(
    skip: int = Query(0, ge=0, description="Number of plants to skip"),
    limit: int = Query(10, ge=1, le=50, description="Max plants to return"),
    beginner_only: bool = Query(False, description="Only show beginner-friendly plants"),
):
    """
    Get paginated list of recommended plants.
    
    - **skip**: Offset for pagination (default: 0)
    - **limit**: Max items per page (default: 10, max: 50)
    - **beginner_only**: Filter for beginner-friendly plants only
    
    Response includes `has_more` flag to indicate if more plants exist.
    """
    plants, total, has_more = await RecommendedPlantsService.get_plants(
        skip=skip,
        limit=limit,
        beginner_only=beginner_only
    )
    
    return RecommendedPlantsListResponse(
        plants=plants,
        total=total,
        has_more=has_more
    )
