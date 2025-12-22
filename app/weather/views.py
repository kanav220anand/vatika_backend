"""Weather API routes."""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.core.exceptions import BadRequestException
from app.auth.service import AuthService
from app.weather.models import WeatherAlertResponse
from app.weather.service import WeatherService

router = APIRouter(prefix="/weather", tags=["Weather"])


@router.get("/alerts/{city}", response_model=WeatherAlertResponse)
async def get_weather_alerts(city: str):
    """
    Get weather alerts and plant care tips for a specific city.
    
    Supported cities include major Indian cities like Mumbai, Delhi, Bangalore, etc.
    """
    service = WeatherService()
    return await service.get_weather_alerts(city)


@router.get("/alerts", response_model=WeatherAlertResponse)
async def get_my_weather_alerts(current_user: dict = Depends(get_current_user)):
    """
    Get weather alerts for your city (from your profile).
    
    Requires authentication and a city set in your profile.
    """
    city = await AuthService.get_user_city(current_user["id"])
    
    if not city:
        raise BadRequestException("Please set your city in your profile first.")
    
    service = WeatherService()
    weather_data = await service.get_weather_alerts(city)

    # Check for meaningful alerts to notify
    if weather_data.alerts:
        from app.notifications.service import NotificationService
        # Only notify for the most severe alert to avoid spam
        top_alert = sorted(weather_data.alerts, key=lambda x: 0 if x.severity == "high" else 1)[0]
        
        await NotificationService.generate_weather_alert(
            user_id=current_user["id"],
            alert_title=f"⚠️ {top_alert.title}",
            alert_message=top_alert.message,
            severity=top_alert.severity
        )
            
    return weather_data

