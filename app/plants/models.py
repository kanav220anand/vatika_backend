"""Plant-related models and schemas."""

from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class PlantHealth(BaseModel):
    """Plant health assessment."""
    status: str = Field(..., description="healthy, stressed, unhealthy")
    confidence: float = Field(..., ge=0, le=1)
    issues: List[str] = Field(default_factory=list)
    immediate_actions: List[str] = Field(default_factory=list)


class CareSchedule(BaseModel):
    """Care schedule for a plant."""
    water_frequency: Dict[str, str] = Field(
        default_factory=dict,
        description="Watering frequency by season: summer, monsoon, winter"
    )
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
    notes: Optional[str] = None


class PlantUpdate(BaseModel):
    """Schema to update a plant."""
    health_status: Optional[str] = None
    notes: Optional[str] = None
    image_url: Optional[str] = None


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
    notes: Optional[str] = None
    last_watered: Optional[datetime] = None
    watering_streak: int = 0  # Consecutive days watered on schedule
    created_at: datetime


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
    image_url: Optional[str] = None
    created_at: datetime


class HealthTimelineResponse(BaseModel):
    """Response containing health snapshots over time."""
    plant_id: str
    snapshots: List[HealthSnapshot]
    total_count: int
