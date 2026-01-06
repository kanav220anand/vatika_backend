"""API routes for city directory/typeahead."""

from fastapi import APIRouter, Query
from app.cities.service import CitiesService
from app.cities.schemas import CitySearchResponse

router = APIRouter(prefix="/cities", tags=["Cities"])


@router.get("", response_model=CitySearchResponse)
async def search_cities(
    query: str = Query("", description="Search text for city/state prefix"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
):
    """
    Case- and whitespace-insensitive city directory search.

    Matches against city or state prefix; results capped by `limit`.
    """
    cities = await CitiesService.search(query=query, limit=limit)
    return CitySearchResponse(cities=cities)
