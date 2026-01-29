#!/usr/bin/env python3
"""
Weather forecast prefetch script for cron jobs and manual triggering.

Usage:
    # Prefetch for a single city
    python -m scripts.prefetch_weather --city mumbai

    # Prefetch for all active user cities
    python -m scripts.prefetch_weather --all

    # Run from repo root
    cd vatika_backend && python -m scripts.prefetch_weather --all

Exit codes:
    0 - Success (all cities prefetched successfully)
    1 - Partial failure (some cities failed, but continued)
    2 - Complete failure or invalid arguments
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

# Make app package importable when run from scripts/ or repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings


# Configure logging for cron-friendly output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_mongo_client(uri: str) -> AsyncIOMotorClient:
    """Create Mongo client with TLS if needed."""
    client_kwargs = {}
    if "mongodb+srv://" in uri or "ssl=true" in uri.lower():
        client_kwargs["tlsCAFile"] = certifi.where()
    return AsyncIOMotorClient(uri, **client_kwargs)


async def get_active_cities_from_db(client: AsyncIOMotorClient, db_name: str) -> list[str]:
    """Get distinct cities from user profiles."""
    db = client[db_name]
    users = db["users"]
    
    # Get distinct cities from users who have a city set
    cities = await users.distinct("city", {"city": {"$exists": True, "$ne": None, "$ne": ""}})
    
    # Normalize and dedupe
    normalized = set()
    for city in cities:
        if city and isinstance(city, str):
            normalized.add(city.lower().strip())
    
    return sorted(normalized)


async def prefetch_single_city(
    client: AsyncIOMotorClient,
    db_name: str,
    city: str,
    api_key: str,
) -> bool:
    """
    Prefetch forecast for a single city using direct API call and cache storage.
    
    This duplicates some logic from WeatherService to avoid needing the full
    FastAPI app context (Database.connect() etc.) for a standalone script.
    """
    import httpx
    from datetime import timedelta, timezone
    
    # Indian cities mapping (copied from service for standalone operation)
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
    
    city_key = city.lower().strip()
    city_display = city.title()
    coords = INDIAN_CITIES.get(city_key)
    
    base_url = "https://api.openweathermap.org/data/2.5"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            if coords:
                url = (
                    f"{base_url}/forecast"
                    f"?lat={coords['lat']}&lon={coords['lon']}"
                    f"&appid={api_key}&units=metric"
                )
            else:
                url = f"{base_url}/forecast?q={city},IN&appid={api_key}&units=metric"
            
            response = await http_client.get(url)
            
            if response.status_code == 404:
                logger.warning(f"City '{city}' not found in OpenWeather API")
                return False
            
            response.raise_for_status()
            data = response.json()
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching forecast for {city}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error fetching forecast for {city}: {e}")
        return False
    
    # Parse forecast list - take next 8 entries (24 hours / 3 hours = 8 buckets)
    forecast_list = data.get("list", [])
    now_ts = datetime.now(timezone.utc)
    
    buckets = []
    for entry in forecast_list:
        entry_ts = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
        
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
        
        if len(buckets) >= 8:
            break
    
    # Store in cache
    db = client[db_name]
    collection = db["weather_forecast_cache"]
    
    now = datetime.utcnow()
    doc = {
        "city_key": city_key,
        "city_display": city_display,
        "lat": coords["lat"] if coords else None,
        "lon": coords["lon"] if coords else None,
        "fetched_at": now,
        "valid_until": now + timedelta(hours=4),
        "forecast": buckets,
    }
    
    await collection.update_one(
        {"city_key": city_key},
        {"$set": doc},
        upsert=True,
    )
    
    logger.info(f"✓ Prefetched {city_key}: {len(buckets)} buckets")
    return True


async def prefetch_all_cities(client: AsyncIOMotorClient, db_name: str, api_key: str) -> tuple[int, int]:
    """
    Prefetch forecasts for all active user cities.
    
    Returns:
        Tuple of (success_count, failure_count)
    """
    cities = await get_active_cities_from_db(client, db_name)
    
    if not cities:
        logger.warning("No active cities found in user profiles")
        return 0, 0
    
    logger.info(f"Prefetching forecasts for {len(cities)} cities: {cities}")
    
    success = 0
    failure = 0
    
    for city in cities:
        try:
            if await prefetch_single_city(client, db_name, city, api_key):
                success += 1
            else:
                failure += 1
        except Exception as e:
            logger.error(f"Unexpected error prefetching {city}: {e}")
            failure += 1
        
        # Small delay between API calls to be nice to OpenWeather
        await asyncio.sleep(0.5)
    
    return success, failure


async def main():
    parser = argparse.ArgumentParser(
        description="Prefetch weather forecasts for caching",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--city",
        type=str,
        help="Prefetch for a single city (e.g., 'mumbai')",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Prefetch for all cities with active users",
    )
    
    args = parser.parse_args()
    
    if not args.city and not args.all:
        parser.error("Must specify either --city <name> or --all")
    
    if args.city and args.all:
        parser.error("Cannot specify both --city and --all")
    
    # Load settings
    settings = get_settings()
    api_key = settings.OPENWEATHER_API_KEY
    
    if not api_key:
        logger.error("OPENWEATHER_API_KEY is not configured")
        sys.exit(2)
    
    # Connect to MongoDB
    mongo_uri = (settings.MONGODB_URI or "").strip() or settings.MONGO_URI
    db_name = settings.MONGO_DB_NAME
    
    # Parse DB name from URI if present
    from urllib.parse import urlparse
    parsed = urlparse(mongo_uri)
    path = (parsed.path or "").lstrip("/")
    if path:
        db_name = path.split("/")[0]
    
    client = get_mongo_client(mongo_uri)
    
    start_time = datetime.utcnow()
    logger.info(f"Weather prefetch started at {start_time.isoformat()}")
    
    try:
        if args.city:
            # Single city mode
            city = args.city.lower().strip()
            success = await prefetch_single_city(client, db_name, city, api_key)
            
            if success:
                logger.info(f"Successfully prefetched forecast for {city}")
                sys.exit(0)
            else:
                logger.error(f"Failed to prefetch forecast for {city}")
                sys.exit(2)
        
        else:
            # All cities mode
            success_count, failure_count = await prefetch_all_cities(client, db_name, api_key)
            
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Prefetch complete: {success_count} success, {failure_count} failed, "
                f"elapsed {elapsed:.1f}s"
            )
            
            if failure_count > 0 and success_count > 0:
                # Partial failure
                sys.exit(1)
            elif failure_count > 0 and success_count == 0:
                # Complete failure
                sys.exit(2)
            else:
                sys.exit(0)
    
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
