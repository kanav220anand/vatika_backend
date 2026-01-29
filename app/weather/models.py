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


# ==================== Forecast Models ====================


class ForecastBucket(BaseModel):
    """A single 3-hour forecast bucket from OpenWeather."""
    ts: datetime = Field(..., description="Timestamp for this forecast bucket (UTC)")
    temp: float = Field(..., description="Temperature in Celsius")
    feels_like: float = Field(..., description="Feels like temperature in Celsius")
    humidity: int = Field(..., description="Humidity percentage")
    description: str = Field(..., description="Weather description (e.g., 'clear sky')")
    wind_speed: float = Field(..., description="Wind speed in m/s")
    rain_3h: Optional[float] = Field(None, description="Rain volume in last 3 hours (mm)")


class ForecastResponse(BaseModel):
    """Response schema for weather forecast endpoint."""
    city: str = Field(..., description="City display name")
    city_key: str = Field(..., description="Normalized city key (lowercase)")
    forecast: List[ForecastBucket] = Field(default_factory=list, description="Next 24h forecast (8 x 3h buckets)")
    current_bucket_index: int = Field(0, description="Index of the bucket closest to current time (for frontend to highlight 'now')")
    fetched_at: datetime = Field(default_factory=datetime.utcnow, description="When the forecast was fetched from OpenWeather")
    from_cache: bool = Field(False, description="Whether this response was served from cache")

