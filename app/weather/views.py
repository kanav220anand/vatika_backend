"""Weather API routes.

This module provides weather forecast endpoints for the Vatisha app.
Uses OpenWeatherMap API with caching for efficient data retrieval.
"""

import logging
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.core.exceptions import BadRequestException
from app.auth.service import AuthService
from app.weather.models import ForecastResponse
from app.weather.service import WeatherService

router = APIRouter(prefix="/weather", tags=["Weather"])
logger = logging.getLogger(__name__)


# ==================== Forecast Endpoints ====================


@router.get("/forecast/{city}", response_model=ForecastResponse)
async def get_weather_forecast(city: str):
    """
    Get 24-hour weather forecast for a specific city.
    
    Returns 8 forecast buckets (3-hour intervals) covering the next 24 hours.
    Includes current_bucket_index to help frontend identify which bucket is "now".
    
    Response is cached for 2 hours for performance. Use the admin prefetch
    endpoint to force-refresh the cache.
    
    Supported cities include major Indian cities like Mumbai, Delhi, Bangalore, etc.
    """
    service = WeatherService()
    return await service.get_forecast_24h(city)


@router.get("/forecast", response_model=ForecastResponse)
async def get_my_weather_forecast(current_user: dict = Depends(get_current_user)):
    """
    Get 24-hour weather forecast for your city (from your profile).
    
    Requires authentication and a city set in your profile.
    Returns 8 forecast buckets (3-hour intervals) covering the next 24 hours.
    """
    city = await AuthService.get_user_city(current_user["id"])
    
    if not city:
        raise BadRequestException("Please set your city in your profile first.")
    
    service = WeatherService()
    return await service.get_forecast_24h(city)
