"""Plants API routes."""

import time
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.core.dependencies import get_current_user
from app.core.config import get_settings
from app.core.exceptions import AppException, BadRequestException
from app.auth.service import AuthService
from app.plants.models import (
    PlantAnalysisRequest,
    PlantAnalysisResponse,
    PlantCreate,
    PlantUpdate,
    PlantResponse,
    CareSchedule,
    PlantBoundary,
    MultiPlantAnalysisRequest,
    MultiPlantDetectionResponse,
    PlantThumbnailAnalysisRequest,
    HealthSnapshot,
    HealthTimelineResponse,
    HealthSnapshotCreateRequest,
    ImmediateFixUpdateRequest,
    PlantEventsResponse,
)
from app.plants.service import PlantService
from app.plants.openai_service import OpenAIService
from app.plants.video_service import VideoService, ImageService, VideoProcessingError
from app.core.aws import S3Service
from app.plants.events_service import EventService
from app.ai.rate_limit import enforce_ai_limits
from app.ai.security import validate_user_owned_s3_key, validate_base64_payload
from app.ai.usage import AIUsageService, AIUsageLog


router = APIRouter(prefix="/plants", tags=["Plants"])
settings = get_settings()


@router.post("/analyze", response_model=PlantAnalysisResponse)
async def analyze_plant(
    request: PlantAnalysisRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Analyze a plant image using AI.
    
    - Identifies the plant species
    - Assesses health condition
    - Provides care instructions tailored for Indian climate
    
    Authentication is required (COST-001).
    """
    await enforce_ai_limits(
        request=http_request,
        user_id=current_user["id"],
        endpoint="plants.analyze",
        per_minute=int(settings.AI_RATE_ANALYZE_PER_MINUTE),
        daily_requests=int(settings.AI_DAILY_REQUESTS),
    )

    city = await AuthService.get_user_city(current_user["id"])

    # Validate that at least one image source is provided
    if not request.image_base64 and not request.image_url:
        raise BadRequestException("Either image_base64 or image_url must be provided")
    
    validate_base64_payload(request.image_base64, max_chars=int(settings.AI_MAX_BASE64_CHARS), field_name="image_base64")
    image_key = None
    if request.image_url:
        image_key = validate_user_owned_s3_key(current_user["id"], request.image_url)
    
    try:
        openai_service = OpenAIService()
        started = time.monotonic()
        try:
            analysis = await openai_service.analyze_plant(
                image_base64=request.image_base64,
                image_url=image_key,
                city=city,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            await AIUsageService.log(
                AIUsageLog(
                    user_id=current_user["id"],
                    endpoint="plants.analyze",
                    model=openai_service.model,
                    status="success",
                    latency_ms=latency_ms,
                )
            )
        except Exception as e:
            latency_ms = int((time.monotonic() - started) * 1000)
            await AIUsageService.log(
                AIUsageLog(
                    user_id=current_user["id"],
                    endpoint="plants.analyze",
                    model=openai_service.model,
                    status="fail",
                    latency_ms=latency_ms,
                    error_type=type(e).__name__,
                )
            )
            raise
        
        # Save to knowledge base (hybrid approach)
        await PlantService.save_to_knowledge_base(analysis)
        
        return analysis
        
    # Avoid masking expected 4xx errors (e.g., request validation) as 500s.
    except AppException:
        raise
    except ValueError as e:
        raise BadRequestException(str(e))
    except Exception as e:
        raise AppException(f"Failed to analyze plant: {str(e)}")


@router.post("/analyze/detect", response_model=MultiPlantDetectionResponse)
async def detect_plants(
    request: MultiPlantAnalysisRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Detect all plants in an image or video.
    
    Returns thumbnails and bounding boxes for each detected plant.
    User can then analyze specific plants using /analyze/thumbnail.
    
    - Supports images (base64)
    - Supports videos (MP4, MOV, WebM up to 50MB)
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    await enforce_ai_limits(
        request=http_request,
        user_id=current_user["id"],
        endpoint="plants.detect",
        per_minute=int(settings.AI_RATE_ANALYZE_PER_MINUTE),
        daily_requests=int(settings.AI_DAILY_REQUESTS),
    )

    city = await AuthService.get_user_city(current_user["id"])
    
    try:
        # Determine source type and get image for analysis
        validate_base64_payload(request.image_base64, max_chars=int(settings.AI_MAX_BASE64_CHARS), field_name="image_base64")
        validate_base64_payload(request.video_base64, max_chars=int(settings.AI_MAX_BASE64_CHARS), field_name="video_base64")

        if request.video_base64 and request.video_mime_type:
            source_type = "video"
            try:
                image_base64 = VideoService.extract_representative_frame(
                    request.video_base64,
                    request.video_mime_type
                )
            except VideoProcessingError as e:
                raise AppException(str(e))
        elif request.image_base64:
            source_type = "image"
            image_base64 = request.image_base64
        elif request.image_url:
            source_type = "image"
            # For detection, we rely on base64 for cropping thumbnails later.
            if not request.image_base64:
                 try:
                     # Download from S3 to get base64 for cropping
                     image_key = validate_user_owned_s3_key(current_user["id"], request.image_url)
                     s3 = S3Service()
                     image_base64 = s3.download_file_as_base64(image_key)
                 except Exception as e:
                     print(f"DEBUG ERROR: Failed to download source image from S3: {e}")
                     # Proceeding without base64 might cause crop failure later if plants detected
                     pass

        
        if not request.image_base64 and not request.video_base64 and not request.image_url:
             raise AppException("Image or video source required")

        # Detect plants using OpenAI
        # Update detect_multiple_plants to accept optional image_url
        openai_service = OpenAIService()
        
        # Note: OpenAIService.detect_multiple_plants signature needs update or we pass kwargs
        # Current signature: detect_multiple_plants(self, image_base64: str, city: Optional[str] = None)
        # We need to update that signature in openai_service.py as well!
        
        # Let's focus on AnalyzeThumbnail first for S3 flow as it's the main saving step
        started = time.monotonic()
        try:
            detected_plants = await openai_service.detect_multiple_plants(
                image_base64=image_base64,
                image_url=None if not request.image_url else validate_user_owned_s3_key(current_user["id"], request.image_url),
                city=city,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            await AIUsageService.log(
                AIUsageLog(
                    user_id=current_user["id"],
                    endpoint="plants.detect",
                    model=openai_service.model,
                    status="success",
                    latency_ms=latency_ms,
                )
            )
        except Exception as e:
            latency_ms = int((time.monotonic() - started) * 1000)
            await AIUsageService.log(
                AIUsageLog(
                    user_id=current_user["id"],
                    endpoint="plants.detect",
                    model=openai_service.model,
                    status="fail",
                    latency_ms=latency_ms,
                    error_type=type(e).__name__,
                )
            )
            raise
        
        # Wait, if we pass URL as image_base64 to detect_multiple_plants, it might fail if that method 
        # specifically expects base64 or doesn't check for URL-like string.
        # Let's check openai_service.py again.
        
        # ... logic continues ...
        
        # Process thumbnails in parallel using thread pool for CPU-bound image operations
        def process_plant(plant):
            try:
                cropped = ImageService.crop_plant_thumbnail(image_base64, plant["bbox"])
                thumbnail = ImageService.create_thumbnail(cropped)
                return PlantBoundary(
                    index=plant["index"],
                    bbox=plant["bbox"],
                    thumbnail_base64=thumbnail,
                    preliminary_name=plant.get("preliminary_name")
                )
            except Exception:
                return None
        
        if not detected_plants:
            results = []
        else:
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=min(len(detected_plants), 4)) as executor:
                tasks = [loop.run_in_executor(executor, process_plant, plant) for plant in detected_plants]
                results = await asyncio.gather(*tasks)
        
        plant_boundaries = [r for r in results if r is not None]
        
        return MultiPlantDetectionResponse(
            detected_count=len(plant_boundaries),
            plants=plant_boundaries,
            source_type=source_type,
            source_image_base64=image_base64  # For context in thumbnail analysis
        )
        
    except AppException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"DEBUG ERROR: {str(e)}")
        raise AppException(f"Failed to detect plants: {str(e)}")


@router.post("/analyze/thumbnail", response_model=PlantAnalysisResponse)
async def analyze_thumbnail(
    request: PlantThumbnailAnalysisRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Analyze a specific plant thumbnail with full health and care information.
    
    Use this after /analyze/detect to get detailed analysis for selected plants.
    """
    await enforce_ai_limits(
        request=http_request,
        user_id=current_user["id"],
        endpoint="plants.thumbnail",
        per_minute=int(settings.AI_RATE_ANALYZE_PER_MINUTE),
        daily_requests=int(settings.AI_DAILY_REQUESTS),
    )

    city = await AuthService.get_user_city(current_user["id"])
    
    try:
        validate_base64_payload(
            request.thumbnail_base64,
            max_chars=int(settings.AI_MAX_BASE64_CHARS),
            field_name="thumbnail_base64",
        )
        validate_base64_payload(
            request.context_image_base64,
            max_chars=int(settings.AI_MAX_BASE64_CHARS),
            field_name="context_image_base64",
        )

        context_key = None
        if request.context_image_url:
            context_key = validate_user_owned_s3_key(current_user["id"], request.context_image_url)

        openai_service = OpenAIService()
        started = time.monotonic()
        try:
            analysis = await openai_service.analyze_plant_thumbnail(
                thumbnail_base64=request.thumbnail_base64 or "",
                city=city,
                context_image_base64=request.context_image_base64,
                context_image_url=context_key,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            await AIUsageService.log(
                AIUsageLog(
                    user_id=current_user["id"],
                    endpoint="plants.thumbnail",
                    model=openai_service.model,
                    status="success",
                    latency_ms=latency_ms,
                )
            )
        except Exception as e:
            latency_ms = int((time.monotonic() - started) * 1000)
            await AIUsageService.log(
                AIUsageLog(
                    user_id=current_user["id"],
                    endpoint="plants.thumbnail",
                    model=openai_service.model,
                    status="fail",
                    latency_ms=latency_ms,
                    error_type=type(e).__name__,
                )
            )
            raise
        
        # Save to knowledge base
        await PlantService.save_to_knowledge_base(analysis)
        
        return analysis
        
    # Avoid masking expected 4xx errors (e.g., request validation) as 500s.
    except AppException:
        raise
    except ValueError as e:
        raise BadRequestException(str(e))
    except Exception as e:
        raise AppException(f"Failed to analyze plant: {str(e)}")


@router.post("", response_model=PlantResponse, status_code=status.HTTP_201_CREATED)
async def save_plant(
    plant_data: PlantCreate,
    current_user: dict = Depends(get_current_user)
):
    """Save a plant to your collection after analysis."""
    return await PlantService.create_plant(current_user["id"], plant_data)


def add_signed_url_to_plant(plant_dict: dict) -> dict:
    """
    Convert S3 key in image_url to a presigned URL.
    Only processes if image_url looks like an S3 key (starts with 'plants/' or 'uploads/').
    """
    if not plant_dict.get("image_url"):
        return plant_dict
    
    image_url = plant_dict["image_url"]
    
    # Only generate presigned URL if it's an S3 key (not already a full URL)
    if image_url.startswith("plants/") or image_url.startswith("uploads/"):
        try:
            s3_service = S3Service()
            # Generate presigned URL valid for 1 hour
            plant_dict["image_url"] = s3_service.generate_presigned_get_url(image_url, expiration=3600)
        except Exception:
            # If presigned URL fails, leave as is
            pass
    
    return plant_dict


@router.get("", response_model=List[PlantResponse])
async def list_plants(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Get plants in your collection with pagination."""
    plants = await PlantService.get_user_plants(current_user["id"], skip=skip, limit=limit)
    # Convert S3 keys to presigned URLs
    return [add_signed_url_to_plant(p.dict() if hasattr(p, 'dict') else dict(p)) for p in plants]


@router.get("/due-for-water", response_model=List[PlantResponse])
async def get_plants_due_for_water(current_user: dict = Depends(get_current_user)):
    """Get plants that need watering today or are overdue."""
    plants = await PlantService.get_plants_needing_water(current_user["id"])
    return [add_signed_url_to_plant(p.dict() if hasattr(p, 'dict') else dict(p)) for p in plants]


@router.get("/search")
async def search_plants(q: str = Query(..., min_length=2)):
    """Search the plant knowledge base by name."""
    return await PlantService.search_knowledge_base(q)


@router.get("/care/{plant_id}", response_model=CareSchedule)
async def get_care_info(plant_id: str):
    """
    Get care information for a plant type.
    
    Use the plant_id from analysis results (e.g., 'monstera_deliciosa').
    """
    return await PlantService.get_care_info(plant_id)


@router.get("/{plant_id}", response_model=PlantResponse)
async def get_plant(
    plant_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific plant from your collection."""
    plant = await PlantService.get_plant_by_id(plant_id, current_user["id"])
    return add_signed_url_to_plant(plant.dict() if hasattr(plant, 'dict') else dict(plant))


@router.patch("/{plant_id}", response_model=PlantResponse)
async def update_plant(
    plant_id: str,
    updates: PlantUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a plant in your collection (health_status, notes, image_url)."""
    plant = await PlantService.update_plant(
        plant_id, 
        current_user["id"], 
        updates.model_dump(exclude_none=True)
    )
    return add_signed_url_to_plant(plant.dict() if hasattr(plant, 'dict') else dict(plant))


@router.delete("/{plant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plant(
    plant_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a plant from your collection."""
    await PlantService.delete_plant(plant_id, current_user["id"])


@router.post("/{plant_id}/water", response_model=PlantResponse)
async def mark_watered(
    plant_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Mark a plant as watered (updates last_watered timestamp)."""
    return await PlantService.mark_watered(plant_id, current_user["id"])


@router.get("/{plant_id}/health-timeline", response_model=HealthTimelineResponse)
async def get_health_timeline(
    plant_id: str,
    limit: int = Query(default=20, le=50),
    current_user: dict = Depends(get_current_user)
):
    """Get the health history timeline for a plant."""
    try:
        snapshots, total = await PlantService.get_health_timeline(
            plant_id, current_user["id"], limit
        )

        # Compute gating info (weekly snapshots)
        next_allowed_at = await PlantService.get_next_allowed_snapshot_at(plant_id, current_user["id"])
        min_days = PlantService._min_days_between_snapshots()

        # Sign S3 keys for timeline images
        s3 = S3Service()
        
        return HealthTimelineResponse(
            plant_id=plant_id,
            snapshots=[
                HealthSnapshot(
                    id=str(s["_id"]),
                    plant_id=s["plant_id"],
                    health_status=s["health_status"],
                    confidence=s.get("confidence", 0.0),
                    issues=s.get("issues", []),
                    immediate_actions=s.get("immediate_actions", []),
                    image_url=(
                        s3.generate_presigned_get_url((s.get("image_key") or s.get("image_url")), expiration=3600)
                        if (s.get("image_key") or s.get("image_url")) and not str(s.get("image_key") or s.get("image_url")).startswith("http")
                        else (s.get("image_key") or s.get("image_url"))
                    ),
                    thumbnail_url=(
                        s3.generate_presigned_get_url(s.get("thumbnail_key"), expiration=3600)
                        if s.get("thumbnail_key") and not str(s.get("thumbnail_key")).startswith("http")
                        else s.get("thumbnail_key")
                    ),
                    snapshot_type=s.get("snapshot_type"),
                    analysis=s.get("analysis"),
                    soil=s.get("soil"),
                    soil_hint=s.get("soil_hint"),
                    created_at=s["created_at"]
                )
                for s in snapshots
            ],
            total_count=total,
            next_allowed_at=next_allowed_at,
            min_days_between_snapshots=min_days,
        )
    except AppException as e:
        raise e
    except Exception as e:
        raise AppException(f"Failed to get health timeline: {str(e)}")


@router.post("/{plant_id}/health-snapshots", response_model=HealthSnapshot, status_code=status.HTTP_201_CREATED)
async def create_health_snapshot(
    plant_id: str,
    request: HealthSnapshotCreateRequest,
    http_request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Add a weekly health snapshot photo for a plant (analyzed automatically)."""
    try:
        await enforce_ai_limits(
            request=http_request,
            user_id=current_user["id"],
            endpoint="plants.snapshot",
            per_minute=int(settings.AI_RATE_GENERIC_PER_MINUTE),
            daily_requests=int(settings.AI_DAILY_REQUESTS),
            daily_snapshots=int(settings.AI_DAILY_SNAPSHOTS),
        )

        image_key = validate_user_owned_s3_key(current_user["id"], request.image_key)
        city = await AuthService.get_user_city(current_user["id"])
        snapshot = await PlantService.create_weekly_health_snapshot(
            plant_id=plant_id,
            user_id=current_user["id"],
            image_key=image_key,
            city=city,
        )

        s3 = S3Service()
        image_key = snapshot.get("image_key")
        thumb_key = snapshot.get("thumbnail_key")

        return HealthSnapshot(
            id=str(snapshot["_id"]),
            plant_id=snapshot["plant_id"],
            health_status=snapshot["health_status"],
            confidence=snapshot.get("confidence", 0.0),
            issues=snapshot.get("issues", []),
            immediate_actions=snapshot.get("immediate_actions", []),
            image_url=s3.generate_presigned_get_url(image_key, expiration=3600) if image_key else None,
            thumbnail_url=s3.generate_presigned_get_url(thumb_key, expiration=3600) if thumb_key else None,
            snapshot_type=snapshot.get("snapshot_type"),
            analysis=snapshot.get("analysis"),
            soil=snapshot.get("soil"),
            soil_hint=snapshot.get("soil_hint"),
            created_at=snapshot["created_at"],
        )
    except AppException as e:
        raise e
    except Exception as e:
        raise AppException(f"Failed to create health snapshot: {str(e)}")


@router.delete("/{plant_id}/health-snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_health_snapshot(
    plant_id: str,
    snapshot_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a health snapshot (also deletes S3 objects)."""
    await PlantService.delete_health_snapshot(plant_id, current_user["id"], snapshot_id)


@router.patch("/{plant_id}/immediate-fixes/{fix_id}", response_model=PlantResponse)
async def update_immediate_fix(
    plant_id: str,
    fix_id: str,
    request: ImmediateFixUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Mark an immediate fix as done/undone (plant owner only)."""
    plant = await PlantService.update_immediate_fix_status(
        plant_id=plant_id,
        user_id=current_user["id"],
        fix_id=fix_id,
        is_done=request.is_done,
    )
    return add_signed_url_to_plant(plant.dict() if hasattr(plant, "dict") else dict(plant))


@router.get("/{plant_id}/events", response_model=PlantEventsResponse)
async def get_plant_events(
    plant_id: str,
    limit: int = Query(default=50, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Get recent plant events (water, photos, health checks)."""
    events = await EventService.get_user_events(user_id=current_user["id"], plant_id=plant_id, limit=limit)
    # Add signed URLs for any image keys stored in event metadata
    s3 = S3Service()
    for e in events:
        meta = e.get("metadata") or {}
        if not isinstance(meta, dict):
            continue

        for key_field, url_field in (("image_key", "image_url"), ("thumbnail_key", "thumbnail_url")):
            if meta.get(url_field):
                continue
            key = meta.get(key_field)
            if isinstance(key, str) and key:
                if key.startswith("http://") or key.startswith("https://"):
                    meta[url_field] = key
                else:
                    try:
                        meta[url_field] = s3.generate_presigned_get_url(key, expiration=3600)
                    except Exception:
                        pass

        e["metadata"] = meta
    return {"events": events}
