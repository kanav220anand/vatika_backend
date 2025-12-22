"""Weather service using OpenWeatherMap API."""

from datetime import datetime, timedelta
from typing import List
import httpx

from app.core.config import get_settings
from app.core.exceptions import NotFoundException, AppException
from app.weather.models import WeatherData, WeatherAlert, WeatherAlertResponse

settings = get_settings()


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

