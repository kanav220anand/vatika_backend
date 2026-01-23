"""
Plantsitter API - Main application entry point.

Urban Gardening Assistant for Indian Balconies.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import Database
from app.core.middleware import MaxBodySizeMiddleware
from app.auth.views import router as auth_router
from app.plants.views import router as plants_router
from app.weather.views import router as weather_router
from app.notifications.views import router as notifications_router
from app.push.views import router as push_router
from app.achievements.views import router as achievements_router
from app.gamification.views import router as gamification_router
from app.recommended_plants.views import router as recommended_plants_router
from app.api.files import router as files_router
from app.cities.views import router as cities_router
from app.articles.views import router as articles_router
from app.care_club.views import router as care_club_router
from app.admin.moderation_views import router as admin_router
from app.jobs.views import router as jobs_router

settings = get_settings()
API_PREFIX = "/api/v1/vatisha"
LEGACY_API_PREFIX = "/api/v1/vatika"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events."""
    # Startup
    await Database.connect()
    yield
    # Shutdown
    await Database.disconnect()


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## Plantsitter API

An intelligent plant care assistant designed for Indian urban balconies.

### Features

- 🌱 **Plant Analysis**: Upload a photo to identify plants and assess their health
- 📅 **Care Schedules**: Get personalized watering and care routines
- 🌤️ **Weather Alerts**: Receive alerts for extreme weather conditions
- 🏠 **Plant Collection**: Manage your plant collection
- 🏆 **Achievements**: Earn achievements for your plant care journey

### Indian Climate Focus

Optimized for Indian conditions:
- Intense summer heat (40°C+)
- Monsoon rainfall and humidity
- Dust and pollution
- Regional variations across cities

    """,
    lifespan=lifespan,
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# COST-001: protect against huge payloads (base64 DoS, etc.)
app.add_middleware(MaxBodySizeMiddleware)

# Include routers
routers = [
    auth_router,
    plants_router,
    weather_router,
    notifications_router,
    push_router,
    achievements_router,
    gamification_router,
    recommended_plants_router,
    files_router,
    cities_router,
    articles_router,
    care_club_router,
    admin_router,
    jobs_router,
]

for router in routers:
    app.include_router(router, prefix=API_PREFIX)
    # Backward compatibility for existing clients (hidden from OpenAPI schema).
    app.include_router(router, prefix=LEGACY_API_PREFIX, include_in_schema=False)


@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "database": "connected" if Database.client else "disconnected",
        "version": settings.APP_VERSION,
    }
