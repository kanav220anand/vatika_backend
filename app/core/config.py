"""
Application configuration using Pydantic Settings.
Loads from environment variables / .env file.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # App
    APP_NAME: str = "Plantsitter API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "plantsitter"
    
    # JWT
    JWT_SECRET_KEY: str = "your-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    
    # OpenWeatherMap
    OPENWEATHER_API_KEY: str = ""
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"



@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()

