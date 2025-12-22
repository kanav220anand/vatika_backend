"""Weather-related models and schemas."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class WeatherData(BaseModel):
    """Current weather data."""
    temperature: float
    feels_like: float
    humidity: int
    description: str
    wind_speed: float
    rain_1h: Optional[float] = None  # Rain volume in last 1 hour (mm)


class WeatherAlert(BaseModel):
    """A weather alert for plant care."""
    type: str = Field(..., description="heatwave, heavy_rain, cold_snap, high_humidity, dust_storm")
    severity: str = Field(..., description="low, medium, high")
    title: str
    message: str
    action: str = Field(..., description="What the user should do")
    valid_until: Optional[datetime] = None


class WeatherAlertResponse(BaseModel):
    """Response schema for weather alerts endpoint."""
    city: str
    current_weather: WeatherData
    alerts: List[WeatherAlert] = Field(default_factory=list)
    plant_tips: List[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

