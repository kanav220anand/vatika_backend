"""
Application configuration using Pydantic Settings.
Loads from environment variables / .env file.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import field_validator


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

    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    AWS_S3_BUCKET: str = ""

    # Public assets base URL (e.g. https://vatika-assets-prod.s3.us-east-1.amazonaws.com/)
    S3_BASE_URL: str = ""

    # Plant timeline (weekly snapshots)
    # Set to 0 to disable the weekly restriction for testing.
    PLANT_TIMELINE_MIN_DAYS_BETWEEN_SNAPSHOTS: int = 7

    @field_validator(
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AWS_S3_BUCKET",
        "S3_BASE_URL",
        mode="before",
    )
    @classmethod
    def _strip_wrapping_quotes(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        # Guard against env values accidentally set to a quoted string (e.g. AWS_S3_BUCKET="bucket")
        if (stripped.startswith('"') and stripped.endswith('"')) or (
            stripped.startswith("'") and stripped.endswith("'")
        ):
            stripped = stripped[1:-1].strip()
        return stripped

    class Config:
        # Allow running from repo root (uses vatika_backend/.env) or from within vatika_backend (uses .env).
        env_file = (".env", "vatika_backend/.env")
        env_file_encoding = "utf-8"



@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
