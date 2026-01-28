"""Weather service using OpenWeatherMap API."""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
import httpx

from app.core.config import get_settings
from app.core.database import Database
from app.core.exceptions import NotFoundException, AppException
from app.weather.models import (
    WeatherData,
    WeatherAlert,
    WeatherAlertResponse,
    ForecastBucket,
    ForecastResponse,
)

settings = get_settings()
logger = logging.getLogger(__name__)

# Cache freshness window (serve from cache if fetched within this time)
FORECAST_CACHE_FRESHNESS_HOURS = 2
# How long until the cache entry is considered "valid" for background prefetch tracking
FORECAST_CACHE_VALID_HOURS = 4


# Indian cities with their coordinates for better accuracy
INDIAN_CITIES = {
    "mumbai": {"lat": 19.076, "lon": 72.8777},
    "delhi": {"lat": 28.6139, "lon": 77.209},
    "bangalore": {"lat": 12.9716, "lon": 77.5946},
    "bengaluru": {"lat": 12.9716, "lon": 77.5946},
    "chennai": {"lat": 13.0827, "lon": 80.2707},
    "kolkata": {"lat": 22.5726, "lon": 88.3639},
    "hyderabad": {"lat": 17.385, "lon": 78.4867},
    "pune": {"lat": 18.5204, "lon": 73.8567},
    "ahmedabad": {"lat": 23.0225, "lon": 72.5714},
    "jaipur": {"lat": 26.9124, "lon": 75.7873},
    "lucknow": {"lat": 26.8467, "lon": 80.9462},
    "chandigarh": {"lat": 30.7333, "lon": 76.7794},
    "kochi": {"lat": 9.9312, "lon": 76.2673},
    "goa": {"lat": 15.2993, "lon": 74.124},
    "noida": {"lat": 28.5355, "lon": 77.391},
    "gurgaon": {"lat": 28.4595, "lon": 77.0266},
    "gurugram": {"lat": 28.4595, "lon": 77.0266},
}


class WeatherService:
    """Handles weather data fetching and plant care alerts."""
    
    _instance: "WeatherService" = None
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.api_key = settings.OPENWEATHER_API_KEY
            cls._instance.base_url = "https://api.openweathermap.org/data/2.5"
        return cls._instance
    
    async def get_weather_alerts(self, city: str) -> WeatherAlertResponse:
        """Get current weather and generate plant care alerts for a city."""
        city_lower = city.lower().strip()
        coords = INDIAN_CITIES.get(city_lower)
        
        try:
            async with httpx.AsyncClient() as client:
                if coords:
                    url = f"{self.base_url}/weather?lat={coords['lat']}&lon={coords['lon']}&appid={self.api_key}&units=metric"
                else:
                    url = f"{self.base_url}/weather?q={city},IN&appid={self.api_key}&units=metric"
                
                response = await client.get(url)
                
                if response.status_code == 404:
                    raise NotFoundException(f"City '{city}' not found. Please check the city name.")
                
                response.raise_for_status()
                data = response.json()
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundException(f"City '{city}' not found. Please check the city name.")
            raise AppException(f"Failed to fetch weather data: {str(e)}")
        except Exception as e:
            if isinstance(e, (NotFoundException, AppException)):
                raise
            raise AppException(f"Failed to fetch weather data: {str(e)}")
        
        # Parse current weather
        current_weather = WeatherData(
            temperature=data["main"]["temp"],
            feels_like=data["main"]["feels_like"],
            humidity=data["main"]["humidity"],
            description=data["weather"][0]["description"],
            wind_speed=data["wind"]["speed"],
            rain_1h=data.get("rain", {}).get("1h"),
        )
        
        # Generate alerts and tips
        alerts = self._generate_alerts(current_weather)
        plant_tips = self._generate_plant_tips(current_weather)
        
        return WeatherAlertResponse(
            city=city.title(),
            current_weather=current_weather,
            alerts=alerts,
            plant_tips=plant_tips,
        )
    
    def _generate_alerts(self, weather: WeatherData) -> List[WeatherAlert]:
        """Generate plant care alerts based on weather conditions."""
        alerts = []
        
        # Heatwave alert
        if weather.temperature >= 40:
            alerts.append(WeatherAlert(
                type="heatwave",
                severity="high",
                title="Extreme Heat Alert",
                message=f"Temperature is {weather.temperature}°C. Your plants are at high risk of heat stress.",
                action="Move shade-loving plants indoors. Water deeply in early morning or evening. Add mulch to pots.",
                valid_until=datetime.utcnow() + timedelta(hours=12),
            ))
        elif weather.temperature >= 35:
            alerts.append(WeatherAlert(
                type="heatwave",
                severity="medium",
                title="High Temperature Warning",
                message=f"Temperature is {weather.temperature}°C. Some plants may need extra care.",
                action="Ensure adequate shade for ferns and tropicals. Increase watering frequency. Mist leaves in evening.",
                valid_until=datetime.utcnow() + timedelta(hours=12),
            ))
        
        # Heavy rain / monsoon alert
        if weather.rain_1h and weather.rain_1h > 10:
            alerts.append(WeatherAlert(
                type="heavy_rain",
                severity="high",
                title="Heavy Rainfall Alert",
                message=f"Heavy rain detected ({weather.rain_1h}mm in last hour). Risk of waterlogging.",
                action="Move potted plants under cover. Check drainage holes. Skip watering for 2-3 days.",
                valid_until=datetime.utcnow() + timedelta(hours=6),
            ))
        elif weather.rain_1h and weather.rain_1h > 5:
            alerts.append(WeatherAlert(
                type="heavy_rain",
                severity="medium",
                title="Rain Alert",
                message="Moderate rainfall. Monitor your plants for waterlogging.",
                action="Ensure pots have proper drainage. Don't water today.",
                valid_until=datetime.utcnow() + timedelta(hours=6),
            ))
        
        # High humidity (fungal risk)
        if weather.humidity >= 85:
            alerts.append(WeatherAlert(
                type="high_humidity",
                severity="medium",
                title="High Humidity Warning",
                message=f"Humidity is {weather.humidity}%. Increased risk of fungal diseases.",
                action="Improve air circulation. Space out plants. Avoid wetting leaves. Watch for fungal spots.",
                valid_until=datetime.utcnow() + timedelta(hours=12),
            ))
        
        # Cold snap (for tropical plants)
        if weather.temperature <= 10:
            alerts.append(WeatherAlert(
                type="cold_snap",
                severity="high",
                title="Cold Weather Alert",
                message=f"Temperature is {weather.temperature}°C. Tropical plants at risk.",
                action="Move tropicals indoors. Group plants together for warmth. Cover sensitive plants overnight.",
                valid_until=datetime.utcnow() + timedelta(hours=12),
            ))
        
        # Dust storm / poor visibility
        weather_desc = weather.description.lower()
        if "dust" in weather_desc or "sand" in weather_desc or "haze" in weather_desc:
            alerts.append(WeatherAlert(
                type="dust_storm",
                severity="medium",
                title="Dust/Haze Alert",
                message="Dusty conditions. Plants may accumulate dust affecting photosynthesis.",
                action="Wipe leaves with damp cloth. Mist plants. Move sensitive plants indoors if possible.",
                valid_until=datetime.utcnow() + timedelta(hours=24),
            ))
        
        return alerts
    
    def _generate_plant_tips(self, weather: WeatherData) -> List[str]:
        """Generate general plant care tips based on current conditions."""
        tips = []
        
        if weather.temperature >= 30:
            tips.append("Water plants in early morning (before 8 AM) or evening (after 6 PM) to reduce evaporation.")
        
        if weather.humidity < 50:
            tips.append("Low humidity: Mist tropical plants or place water trays near them for humidity.")
        
        if weather.humidity > 70:
            tips.append("High humidity: Reduce watering frequency and watch for fungal issues.")
        
        if weather.temperature < 20:
            tips.append("Cool weather: Reduce watering. Most plants need less water in cooler temperatures.")
        
        # Seasonal tip based on month
        month = datetime.utcnow().month
        if month in [4, 5, 6]:
            tips.append("Peak summer: Consider shade cloth for west-facing balconies to protect from afternoon sun.")
        elif month in [7, 8, 9]:
            tips.append("Monsoon season: Check drainage regularly. Reduce fertilizer. Watch for pests.")
        elif month in [10, 11]:
            tips.append("Post-monsoon: Good time to repot and fertilize. Plants are entering growth phase.")
        elif month in [12, 1, 2]:
            tips.append("Winter: Reduce watering. Move cold-sensitive plants to warmer spots.")
        
        return tips

    # ==================== Forecast Methods ====================

    def _get_city_coords(self, city: str) -> Tuple[Optional[dict], str, str]:
        """
        Get coordinates for a city from INDIAN_CITIES mapping.
        
        Returns:
            Tuple of (coords_dict or None, city_key, city_display)
        """
        city_key = city.lower().strip()
        city_display = city.title()
        coords = INDIAN_CITIES.get(city_key)
        return coords, city_key, city_display

    async def _get_forecast_from_cache(self, city_key: str) -> Optional[dict]:
        """
        Check if we have a fresh forecast in the cache.
        
        Returns the cached document if fresh (within FORECAST_CACHE_FRESHNESS_HOURS),
        otherwise returns None.
        """
        collection = Database.get_collection("weather_forecast_cache")
        cached = await collection.find_one({"city_key": city_key})
        
        if not cached:
            return None
        
        fetched_at = cached.get("fetched_at")
        if not fetched_at:
            return None
        
        # Check freshness
        freshness_cutoff = datetime.utcnow() - timedelta(hours=FORECAST_CACHE_FRESHNESS_HOURS)
        if fetched_at < freshness_cutoff:
            logger.debug(f"Cache stale for {city_key}: fetched_at={fetched_at}")
            return None
        
        logger.debug(f"Cache hit for {city_key}")
        return cached

    async def _store_forecast_in_cache(
        self,
        city_key: str,
        city_display: str,
        lat: Optional[float],
        lon: Optional[float],
        forecast_buckets: List[dict],
    ) -> None:
        """Store forecast data in the cache collection."""
        collection = Database.get_collection("weather_forecast_cache")
        
        now = datetime.utcnow()
        doc = {
            "city_key": city_key,
            "city_display": city_display,
            "lat": lat,
            "lon": lon,
            "fetched_at": now,
            "valid_until": now + timedelta(hours=FORECAST_CACHE_VALID_HOURS),
            "forecast": forecast_buckets,
        }
        
        # Upsert by city_key
        await collection.update_one(
            {"city_key": city_key},
            {"$set": doc},
            upsert=True,
        )
        logger.info(f"Stored forecast cache for {city_key} ({len(forecast_buckets)} buckets)")

    async def _fetch_forecast_from_api(
        self, city: str, coords: Optional[dict], city_key: str
    ) -> List[dict]:
        """
        Fetch 24-hour forecast from OpenWeatherMap API.
        
        Returns list of forecast bucket dicts (raw, for storage).
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if coords:
                    url = (
                        f"{self.base_url}/forecast"
                        f"?lat={coords['lat']}&lon={coords['lon']}"
                        f"&appid={self.api_key}&units=metric"
                    )
                else:
                    url = (
                        f"{self.base_url}/forecast"
                        f"?q={city},IN&appid={self.api_key}&units=metric"
                    )
                
                response = await client.get(url)
                
                if response.status_code == 404:
                    raise NotFoundException(f"City '{city}' not found. Please check the city name.")
                
                response.raise_for_status()
                data = response.json()
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundException(f"City '{city}' not found. Please check the city name.")
            raise AppException(f"Failed to fetch forecast data: {str(e)}")
        except Exception as e:
            if isinstance(e, (NotFoundException, AppException)):
                raise
            raise AppException(f"Failed to fetch forecast data: {str(e)}")
        
        # Parse forecast list - take next 8 entries (24 hours / 3 hours = 8 buckets)
        forecast_list = data.get("list", [])
        now_ts = datetime.now(timezone.utc)
        
        # Filter to entries within the next 24 hours
        buckets = []
        for entry in forecast_list:
            # OpenWeather returns "dt" as Unix timestamp
            entry_ts = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
            
            # Only include forecasts from now to now + 24h
            if entry_ts < now_ts:
                continue
            if entry_ts > now_ts + timedelta(hours=24):
                break
            
            bucket = {
                "ts": entry_ts.replace(tzinfo=None),  # Store as naive UTC
                "temp": entry["main"]["temp"],
                "feels_like": entry["main"]["feels_like"],
                "humidity": entry["main"]["humidity"],
                "description": entry["weather"][0]["description"] if entry.get("weather") else "",
                "wind_speed": entry["wind"]["speed"] if entry.get("wind") else 0.0,
                "rain_3h": entry.get("rain", {}).get("3h"),
            }
            buckets.append(bucket)
            
            # Limit to 8 buckets (24 hours)
            if len(buckets) >= 8:
                break
        
        logger.info(f"Fetched {len(buckets)} forecast buckets from API for {city_key}")
        return buckets

    def _compute_current_bucket_index(self, forecast_buckets: List[dict]) -> int:
        """
        Compute the index of the bucket that is closest to "now" or the first future bucket.
        
        Returns 0 if no future bucket found (fallback to first bucket).
        """
        if not forecast_buckets:
            return 0
        
        now = datetime.utcnow()
        
        for i, bucket in enumerate(forecast_buckets):
            bucket_ts = bucket.get("ts")
            if bucket_ts and bucket_ts >= now:
                return i
        
        # All buckets are in the past, return last bucket
        return len(forecast_buckets) - 1

    async def get_forecast_24h(self, city: str, force_refresh: bool = False) -> ForecastResponse:
        """
        Get 24-hour forecast for a city.
        
        Uses cache-first strategy:
        - If fresh cache exists (within FORECAST_CACHE_FRESHNESS_HOURS), return from cache
        - Otherwise fetch from OpenWeather, store in cache, and return
        
        Args:
            city: City name (will be normalized)
            force_refresh: If True, bypass cache and fetch fresh data
            
        Returns:
            ForecastResponse with forecast buckets and metadata
        """
        coords, city_key, city_display = self._get_city_coords(city)
        
        # Check cache first (unless force_refresh)
        from_cache = False
        forecast_buckets = None
        fetched_at = None
        
        if not force_refresh:
            cached = await self._get_forecast_from_cache(city_key)
            if cached:
                forecast_buckets = cached.get("forecast", [])
                fetched_at = cached.get("fetched_at")
                from_cache = True
                # Update city_display from cache if available
                if cached.get("city_display"):
                    city_display = cached["city_display"]
        
        # Fetch from API if no cache or forced refresh
        if forecast_buckets is None:
            forecast_buckets = await self._fetch_forecast_from_api(city, coords, city_key)
            fetched_at = datetime.utcnow()
            
            # Store in cache
            lat = coords["lat"] if coords else None
            lon = coords["lon"] if coords else None
            await self._store_forecast_in_cache(city_key, city_display, lat, lon, forecast_buckets)
        
        # Compute current bucket index
        current_bucket_index = self._compute_current_bucket_index(forecast_buckets)
        
        # Convert to pydantic models
        forecast_models = [ForecastBucket(**b) for b in forecast_buckets]
        
        return ForecastResponse(
            city=city_display,
            city_key=city_key,
            forecast=forecast_models,
            current_bucket_index=current_bucket_index,
            fetched_at=fetched_at or datetime.utcnow(),
            from_cache=from_cache,
        )

    async def prefetch_forecast_for_city(self, city: str) -> bool:
        """
        Prefetch forecast for a city (force refresh and store in cache).
        
        Used by cron jobs and admin endpoints.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            await self.get_forecast_24h(city, force_refresh=True)
            return True
        except Exception as e:
            logger.error(f"Failed to prefetch forecast for {city}: {e}")
            return False

    @staticmethod
    async def get_active_user_cities() -> List[str]:
        """
        Get list of distinct cities from user profiles.
        
        Used by cron prefetch to determine which cities to prefetch.
        
        Returns:
            List of unique city names (normalized lowercase)
        """
        collection = Database.get_collection("users")
        
        # Get distinct cities from users who have a city set
        cities = await collection.distinct("city", {"city": {"$exists": True, "$ne": None, "$ne": ""}})
        
        # Normalize and dedupe
        normalized = set()
        for city in cities:
            if city and isinstance(city, str):
                normalized.add(city.lower().strip())
        
        return list(normalized)

