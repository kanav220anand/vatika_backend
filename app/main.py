"""
Plantsitter API - Main application entry point.

Urban Gardening Assistant for Indian Balconies.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import Database
from app.auth import auth_router
from app.plants import plants_router
from app.weather import weather_router
from app.notifications.views import router as notifications_router
from app.achievements.views import router as achievements_router
from app.gamification.views import router as gamification_router
from app.recommended_plants import recommended_plants_router
from app.api.files import router as files_router
from app.cities import cities_router

settings = get_settings()


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
    docs_url="/api/v1/vatika/docs",
    redoc_url="/api/v1/vatika/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/api/v1/vatika")
app.include_router(plants_router, prefix="/api/v1/vatika")
app.include_router(weather_router, prefix="/api/v1/vatika")
app.include_router(notifications_router, prefix="/api/v1/vatika")
app.include_router(achievements_router, prefix="/api/v1/vatika")
app.include_router(gamification_router, prefix="/api/v1/vatika")
app.include_router(recommended_plants_router, prefix="/api/v1/vatika")
app.include_router(files_router, prefix="/api/v1/vatika")
app.include_router(cities_router, prefix="/api/v1/vatika")


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
