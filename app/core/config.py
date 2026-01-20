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
    # Optional combined URI (includes DB name), used by Celery worker + jobs tooling.
    # Example: mongodb://localhost:27017/vatika
    MONGODB_URI: str = ""
    
    # JWT
    JWT_SECRET_KEY: str = "your-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # COST-001: API hardening for AI spend control
    MAX_REQUEST_BODY_BYTES: int = 2_000_000
    AI_MAX_CONCURRENT: int = 10
    AI_OPENAI_TIMEOUT_SECONDS: int = 45
    AI_MAX_S3_IMAGE_BYTES: int = 8_000_000
    AI_MAX_BASE64_CHARS: int = 120_000  # legacy support; prefer S3 keys

    AI_RATE_PER_IP_PER_MINUTE: int = 60
    AI_RATE_ANALYZE_PER_MINUTE: int = 10
    AI_RATE_GENERIC_PER_MINUTE: int = 30

    AI_DAILY_REQUESTS: int = 50
    AI_DAILY_SNAPSHOTS: int = 10
    
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

    # ------------------------------------------------------------------
    # ANALYSIS-002: Soil signals (day-shift modifiers)
    # ------------------------------------------------------------------
    SOIL_CONFIDENCE_THRESHOLD: float = 0.6
    SOIL_MAX_AGE_DAYS: int = 3
    SOIL_RECENT_WATERING_IGNORE_HOURS: int = 24
    SOIL_SHIFT_MAX_DAYS: int = 2

    # Watering streak timing grace windows (schedule-aware streaks)
    WATERING_GRACE_DAYS_EARLY: int = 1
    WATERING_GRACE_DAYS_LATE: int = 1

    # Admin moderation (Postman-only MVP)
    ADMIN_API_KEY: str = ""

    # Care Club rate limits (per 24 hours)
    CARE_CLUB_POSTS_PER_24H: int = 3
    CARE_CLUB_COMMENTS_PER_24H: int = 10
    CARE_CLUB_HELPFUL_VOTES_PER_24H: int = 30

    # ------------------------------------------------------------------
    # INFRA-001 / JOBS-001: Celery (SQS broker) + Mongo jobs store
    # ------------------------------------------------------------------
    CELERY_BROKER_URL: str = "sqs://"
    CELERY_QUEUE_PREFIX: str = "vatika-"
    SQS_DEFAULT_QUEUE_NAME: str = "vatika-default"
    SQS_DEFAULT_QUEUE_URL: str = ""

    CELERY_VISIBILITY_TIMEOUT: int = 3600
    CELERY_POLLING_INTERVAL: float = 1
    CELERY_WAIT_TIME_SECONDS: int = 10
    CELERY_TASK_TIME_LIMIT: int = 420
    CELERY_TASK_SOFT_TIME_LIMIT: int = 360

    JOBS_RETENTION_DAYS: int = 30
    DEBUG_JOBS_ENDPOINTS: bool = False
    JOBS_MAX_INPUT_BYTES: int = 20_000
    JOBS_IDEMPOTENCY_WINDOW_HOURS: int = 6

    @field_validator(
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AWS_S3_BUCKET",
        "S3_BASE_URL",
        "MONGODB_URI",
        "CELERY_BROKER_URL",
        "CELERY_QUEUE_PREFIX",
        "SQS_DEFAULT_QUEUE_NAME",
        "SQS_DEFAULT_QUEUE_URL",
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
