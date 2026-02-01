"""Plant-related models and schemas."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


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


class PlantToxicity(BaseModel):
    """Toxicity / pet safety profile."""

    cats: str = Field(default="unknown", description="safe | mildly_toxic | toxic | unknown")
    dogs: str = Field(default="unknown", description="safe | mildly_toxic | toxic | unknown")
    humans: str = Field(default="unknown", description="safe | irritant | toxic | unknown")
    severity: str = Field(default="unknown", description="low | medium | high | unknown")
    summary: Optional[str] = Field(default=None, description="1–2 lines max, calm tone")
    symptoms: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


class PlantPlacement(BaseModel):
    """Indoor/outdoor classification and practical placement guidance."""

    typical_environment: str = Field(default="unknown", description="indoor | outdoor | both | unknown")
    recommended_environment: str = Field(default="unknown", description="indoor | outdoor | both | unknown")
    reason: Optional[str] = None
    indoor_tips: List[str] = Field(default_factory=list)
    outdoor_tips: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


# ==================== Soil Models (ANALYSIS-002) ====================


class SoilDryness(str, Enum):
    VERY_DRY = "very_dry"
    DRY = "dry"
    MOIST = "moist"
    WET = "wet"
    WATERLOGGED = "waterlogged"
    UNKNOWN = "unknown"


class SoilStructure(str, Enum):
    COMPACTED = "compacted"
    NORMAL = "normal"
    AIRY = "airy"
    UNKNOWN = "unknown"


class SoilDrainageRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class SoilLikelihood(str, Enum):
    NONE = "none"
    POSSIBLE = "possible"
    LIKELY = "likely"
    UNKNOWN = "unknown"


class SoilRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class TopsoilCoverage(str, Enum):
    GOOD = "good"
    PATCHY = "patchy"
    BARE = "bare"
    UNKNOWN = "unknown"


class DebrisLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class HintStatus(str, Enum):
    OK = "ok"
    WATCH = "watch"
    ACTION = "action"


class SoilSurfaceSignals(BaseModel):
    mold_or_algae: SoilLikelihood = SoilLikelihood.UNKNOWN
    salt_crust: SoilLikelihood = SoilLikelihood.UNKNOWN
    fungus_gnats_risk: SoilRisk = SoilRisk.UNKNOWN


class SoilTopLayer(BaseModel):
    mulch_present: Optional[bool] = None
    topsoil_coverage: TopsoilCoverage = TopsoilCoverage.UNKNOWN
    debris_level: DebrisLevel = DebrisLevel.UNKNOWN


class SoilAssessment(BaseModel):
    visible: bool = False
    confidence: float = Field(default=0.0, ge=0, le=1)
    dryness: SoilDryness = SoilDryness.UNKNOWN
    structure: SoilStructure = SoilStructure.UNKNOWN
    drainage_risk: SoilDrainageRisk = SoilDrainageRisk.UNKNOWN
    surface_signals: SoilSurfaceSignals = Field(default_factory=SoilSurfaceSignals)
    top_layer: SoilTopLayer = Field(default_factory=SoilTopLayer)
    evidence: List[str] = Field(default_factory=list, description="Max 4 short cues")
    notes: Optional[str] = Field(default=None, description="<= 200 chars")
    observed_at: Optional[datetime] = None


class SoilState(BaseModel):
    visible: bool = False
    confidence: float = Field(default=0.0, ge=0, le=1)
    dryness: SoilDryness = SoilDryness.UNKNOWN
    observed_at: datetime


class SoilHint(BaseModel):
    status: HintStatus
    headline: str = Field(..., max_length=60)
    action: str = Field(..., max_length=90)
    confidence: float = Field(default=0.0, ge=0, le=1)
    relevant_factors: List[str] = Field(default_factory=list, description="Max 4")


class PlantAnalysisResponse(BaseModel):
    """Response schema for plant analysis."""
    plant_id: str = Field(..., description="Normalized plant identifier")
    scientific_name: str
    common_name: str
    plant_family: str = Field(..., description="One of PlantFamily enum values")
    confidence: float = Field(..., ge=0, le=1)
    health: PlantHealth
    care: CareSchedule
    toxicity: Optional[PlantToxicity] = None
    placement: Optional[PlantPlacement] = None
    soil: Optional["SoilAssessment"] = None


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
    toxicity: Optional[PlantToxicity] = None
    placement: Optional[PlantPlacement] = None
    soil: Optional["SoilAssessment"] = None
    last_analysis_at: Optional[datetime] = None
    last_watered: Optional[datetime] = Field(
        default=None,
        description="When the user last watered the plant (optional; can be estimated if unknown).",
    )
    last_watered_source: Optional[str] = Field(
        default=None,
        description="user_exact | user_estimate | unknown",
    )
    notes: Optional[str] = None
    care_schedule: Optional[CareScheduleStored] = None  # Stored care data
    reminders_enabled: bool = True


class PlantUpdate(BaseModel):
    """Schema to update a plant."""
    nickname: Optional[str] = None
    health_status: Optional[str] = None
    notes: Optional[str] = None
    image_url: Optional[str] = None
    reminders_enabled: Optional[bool] = None


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
    last_watered_source: Optional[str] = Field(
        default=None,
        description="user_exact | user_estimate | unknown",
    )
    watering_streak: int = 0  # Consecutive days watered on schedule
    created_at: datetime
    # Care reminder fields
    care_schedule: Optional[CareScheduleStored] = None
    reminders_enabled: bool = True
    next_water_date: Optional[datetime] = None  # Calculated field
    last_health_check: Optional[datetime] = None
    last_event_at: Optional[datetime] = Field(
        default=None,
        description="Most recent plant event time (water/photo/health/etc.)",
    )
    toxicity: Optional[PlantToxicity] = None
    placement: Optional[PlantPlacement] = None
    soil_state: Optional["SoilState"] = None
    initial_snapshot_id: Optional[str] = None
    last_analysis_at: Optional[datetime] = None


class PlantEventResponse(BaseModel):
    """Response schema for a plant event (history timeline)."""
    id: str
    event_type: str
    plant_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    # Enriched watering context (optional/backward compatible)
    occurred_at: Optional[datetime] = None
    recommended_at: Optional[datetime] = None
    timing: Optional[str] = None  # early | on_time | late
    delta_days: Optional[int] = None
    streak_before: Optional[int] = None
    streak_after: Optional[int] = None
    next_water_date_before: Optional[datetime] = None
    next_water_date_after: Optional[datetime] = None


class PlantEventsResponse(BaseModel):
    """Response containing list of plant events."""
    events: List[PlantEventResponse]


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
    snapshot_type: Optional[str] = Field(default=None, description="initial | progress")
    analysis: Optional[Dict[str, Any]] = None
    soil: Optional["SoilAssessment"] = None
    soil_hint: Optional["SoilHint"] = None
    created_at: datetime


class HealthTimelineResponse(BaseModel):
    """Response containing health snapshots over time."""
    plant_id: str
    snapshots: List[HealthSnapshot]
    total_count: int
    next_allowed_at: Optional[datetime] = None
    min_days_between_snapshots: int = 7


class HealthSnapshotCreateRequest(BaseModel):
    """Create a new health snapshot from an uploaded image or base64 data."""
    image_key: Optional[str] = Field(None, description="S3 key for the uploaded image (used for storage)")
    image_base64: Optional[str] = Field(None, description="Base64 encoded image for analysis (skip S3 download)")
    thumbnail_base64: Optional[str] = Field(None, description="Base64 encoded thumbnail (skip thumbnail generation)")
    note: Optional[str] = Field(None, max_length=500, description="Optional note to add with this snapshot")


# ==================== Plant Journal Models ====================


class JournalEntryType(str, Enum):
    """Types of journal entries."""
    NOTE = "note"  # General note
    REPOTTED = "repotted"
    MOVED = "moved"
    FERTILIZED = "fertilized"
    PRUNED = "pruned"
    PROPAGATED = "propagated"
    NEW_GROWTH = "new_growth"
    FLOWERING = "flowering"
    PEST_SPOTTED = "pest_spotted"
    OTHER = "other"


class JournalEntryCreate(BaseModel):
    """Create a new journal entry."""
    entry_type: JournalEntryType = JournalEntryType.NOTE
    content: str = Field(..., min_length=1, max_length=1000, description="Journal entry content")
    image_key: Optional[str] = Field(None, description="Optional S3 key for an attached image")


class JournalEntryUpdate(BaseModel):
    """Update a journal entry."""
    content: Optional[str] = Field(None, min_length=1, max_length=1000)
    entry_type: Optional[JournalEntryType] = None


class JournalEntry(BaseModel):
    """A journal entry for a plant."""
    id: str
    plant_id: str
    user_id: str
    entry_type: str
    content: str
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class JournalResponse(BaseModel):
    """Response containing journal entries."""
    entries: List[JournalEntry]
    total_count: int
    has_more: bool = False
