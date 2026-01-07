"""Plant-related models and schemas."""

from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class PlantHealth(BaseModel):
    """Plant health assessment."""
    status: str = Field(..., description="healthy, stressed, unhealthy")
    confidence: float = Field(..., ge=0, le=1)
    primary_issue: str = Field(..., description="Dominant issue tag (must match articles.issue_tags)")
    severity: str = Field(..., description="low, medium, high")
    issues: List[str] = Field(default_factory=list)
    immediate_actions: List[str] = Field(default_factory=list)


class CareSchedule(BaseModel):
    """Care schedule for a plant (from OpenAI analysis)."""
    water_frequency: Dict[str, str] = Field(
        default_factory=dict,
        description="Watering frequency by season: summer, monsoon, winter"
    )
    light_preference: str = Field(default="bright_indirect")
    humidity: str = Field(default="medium")
    fertilizer_frequency: Optional[str] = None
    indian_climate_tips: List[str] = Field(default_factory=list)


class WateringSchedule(BaseModel):
    """Watering schedule with integer days per season."""
    summer: int = Field(default=3, description="Days between watering in summer")
    monsoon: int = Field(default=5, description="Days between watering in monsoon")
    winter: int = Field(default=7, description="Days between watering in winter")


class CareScheduleStored(BaseModel):
    """Care schedule stored with plant (integer days for calculations)."""
    watering: WateringSchedule = Field(default_factory=WateringSchedule)
    light_preference: str = Field(default="bright_indirect")
    humidity: str = Field(default="medium")
    fertilizer_frequency: Optional[str] = None
    indian_climate_tips: List[str] = Field(default_factory=list)


class PlantAnalysisRequest(BaseModel):
    """Request schema for plant analysis."""
    image_base64: Optional[str] = Field(None, description="Base64 encoded plant image")
    image_url: Optional[str] = Field(None, description="S3 Key or URL of plant image")


class PlantAnalysisResponse(BaseModel):
    """Response schema for plant analysis."""
    plant_id: str = Field(..., description="Normalized plant identifier")
    scientific_name: str
    common_name: str
    plant_family: str = Field(..., description="One of PlantFamily enum values")
    confidence: float = Field(..., ge=0, le=1)
    health: PlantHealth
    care: CareSchedule


class PlantCreate(BaseModel):
    """Schema to save a plant to user's collection."""
    plant_id: str
    scientific_name: str
    common_name: str
    nickname: Optional[str] = None  # User-given name for the plant
    image_url: Optional[str] = None
    health_status: str = "healthy"
    # Analysis metadata (used by downstream systems like articles)
    plant_family: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    # Optional full analysis payloads (sent by clients after /analyze)
    care: Optional[CareSchedule] = None
    health: Optional[PlantHealth] = None
    last_watered: Optional[datetime] = Field(
        default=None,
        description="When the user last watered the plant (optional; can be estimated if unknown).",
    )
    notes: Optional[str] = None
    care_schedule: Optional[CareScheduleStored] = None  # Stored care data
    reminders_enabled: bool = True


class PlantUpdate(BaseModel):
    """Schema to update a plant."""
    health_status: Optional[str] = None
    notes: Optional[str] = None
    image_url: Optional[str] = None


class ImmediateFixItem(BaseModel):
    """Actionable, user-trackable immediate fix for a plant."""

    id: str
    action: str
    is_done: bool = False
    created_at: datetime
    completed_at: Optional[datetime] = None


class ImmediateFixUpdateRequest(BaseModel):
    """Toggle completion of an immediate fix."""

    is_done: bool = Field(..., description="Mark fix as done/undone")


class PlantResponse(BaseModel):
    """Response schema for a saved plant."""
    id: str
    user_id: str
    plant_id: str
    scientific_name: str
    common_name: str
    nickname: Optional[str] = None  # User-given name for the plant
    image_url: Optional[str] = None
    health_status: str
    health_confidence: Optional[float] = None
    health_primary_issue: Optional[str] = None
    health_severity: Optional[str] = None
    confidence_bucket: Optional[str] = None
    plant_family: Optional[str] = None
    health_score: Optional[int] = Field(default=None, ge=0, le=100)
    health_issues: List[str] = Field(default_factory=list)
    health_immediate_actions: List[str] = Field(default_factory=list)
    immediate_fixes: List[ImmediateFixItem] = Field(default_factory=list)
    notes: Optional[str] = None
    last_watered: Optional[datetime] = None
    watering_streak: int = 0  # Consecutive days watered on schedule
    created_at: datetime
    # Care reminder fields
    care_schedule: Optional[CareScheduleStored] = None
    reminders_enabled: bool = True
    next_water_date: Optional[datetime] = None  # Calculated field
    last_health_check: Optional[datetime] = None


# ==================== Multi-Plant Detection Models ====================


class PlantBoundary(BaseModel):
    """Bounding box and thumbnail for a detected plant."""
    index: int = Field(..., description="Index of this plant in the detection")
    bbox: Dict[str, float] = Field(
        ..., 
        description="Bounding box with x, y, width, height (normalized 0-1)"
    )
    thumbnail_base64: str = Field(..., description="Base64 encoded thumbnail image")
    preliminary_name: Optional[str] = Field(
        None, 
        description="Quick identification before full analysis"
    )


class MultiPlantAnalysisRequest(BaseModel):
    """Request for analyzing image/video with multiple plants."""
    image_base64: Optional[str] = Field(None, description="Base64 encoded image")
    image_url: Optional[str] = Field(None, description="S3 Key or URL of image")
    video_base64: Optional[str] = Field(None, description="Base64 encoded video")
    video_url: Optional[str] = Field(None, description="S3 Key or URL of video")
    video_mime_type: Optional[str] = Field(
        None, 
        description="MIME type for video (video/mp4, video/quicktime, etc.)"
    )


class MultiPlantDetectionResponse(BaseModel):
    """Initial detection response with thumbnails for all detected plants."""
    detected_count: int = Field(..., description="Number of plants detected")
    plants: List[PlantBoundary] = Field(
        default_factory=list, 
        description="List of detected plants with thumbnails"
    )
    source_type: str = Field(..., description="'image' or 'video'")
    source_image_base64: Optional[str] = Field(
        None,
        description="The image used for detection (for context in thumbnail analysis)"
    )


class PlantThumbnailAnalysisRequest(BaseModel):
    """Request to analyze a specific plant from thumbnails."""
    thumbnail_base64: Optional[str] = Field(None, description="Base64 encoded plant thumbnail")
    thumbnail_url: Optional[str] = Field(None, description="S3 Key or URL of thumbnail")
    context_image_base64: Optional[str] = Field(
        None, 
        description="Full image for additional context"
    )
    context_image_url: Optional[str] = Field(
        None, 
        description="S3 Key or URL of context image"
    )


# ==================== Health Timeline Models ====================


class HealthSnapshot(BaseModel):
    """A point-in-time health assessment for a plant."""
    id: str
    plant_id: str
    health_status: str
    confidence: float = 0.0
    issues: List[str] = Field(default_factory=list)
    immediate_actions: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    created_at: datetime


class HealthTimelineResponse(BaseModel):
    """Response containing health snapshots over time."""
    plant_id: str
    snapshots: List[HealthSnapshot]
    total_count: int
    next_allowed_at: Optional[datetime] = None
    min_days_between_snapshots: int = 7


class HealthSnapshotCreateRequest(BaseModel):
    """Create a new health snapshot from an uploaded image key."""
    image_key: str = Field(..., description="S3 key for the uploaded image")
