"""Plants API routes."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_current_user, get_current_user_optional
from app.core.exceptions import AppException
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
)
from app.plants.service import PlantService
from app.plants.openai_service import OpenAIService
from app.plants.video_service import VideoService, ImageService, VideoProcessingError


router = APIRouter(prefix="/plants", tags=["Plants"])


@router.post("/analyze", response_model=PlantAnalysisResponse)
async def analyze_plant(
    request: PlantAnalysisRequest,
    current_user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    Analyze a plant image using AI.
    
    - Identifies the plant species
    - Assesses health condition
    - Provides care instructions tailored for Indian climate
    
    Authentication is optional but provides better context (user's city).
    """
    # Get user's city for context if authenticated
    city = None
    if current_user:
        city = await AuthService.get_user_city(current_user["id"])
    
    try:
        openai_service = OpenAIService()
        analysis = await openai_service.analyze_plant(request.image_base64, city)
        
        # Save to knowledge base (hybrid approach)
        await PlantService.save_to_knowledge_base(analysis)
        
        return analysis
        
    except Exception as e:
        raise AppException(f"Failed to analyze plant: {str(e)}")


@router.post("/analyze/detect", response_model=MultiPlantDetectionResponse)
async def detect_plants(
    request: MultiPlantAnalysisRequest,
    current_user: Optional[dict] = Depends(get_current_user_optional)
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
    
    # Get user's city for context if authenticated
    city = None
    if current_user:
        city = await AuthService.get_user_city(current_user["id"])
    
    try:
        # Determine source type and get image for analysis
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
        else:
            raise AppException("Either image_base64 or video_base64 with video_mime_type is required")
        
        # Detect plants using OpenAI
        openai_service = OpenAIService()
        detected_plants = await openai_service.detect_multiple_plants(image_base64, city)
        
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
        raise AppException(f"Failed to detect plants: {str(e)}")


@router.post("/analyze/thumbnail", response_model=PlantAnalysisResponse)
async def analyze_thumbnail(
    request: PlantThumbnailAnalysisRequest,
    current_user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    Analyze a specific plant thumbnail with full health and care information.
    
    Use this after /analyze/detect to get detailed analysis for selected plants.
    """
    city = None
    if current_user:
        city = await AuthService.get_user_city(current_user["id"])
    
    try:
        openai_service = OpenAIService()
        analysis = await openai_service.analyze_plant_thumbnail(
            request.thumbnail_base64,
            city,
            request.context_image_base64
        )
        
        # Save to knowledge base
        await PlantService.save_to_knowledge_base(analysis)
        
        return analysis
        
    except Exception as e:
        raise AppException(f"Failed to analyze plant: {str(e)}")


@router.post("", response_model=PlantResponse, status_code=status.HTTP_201_CREATED)
async def save_plant(
    plant_data: PlantCreate,
    current_user: dict = Depends(get_current_user)
):
    """Save a plant to your collection after analysis."""
    return await PlantService.create_plant(current_user["id"], plant_data)


@router.get("", response_model=List[PlantResponse])
async def list_plants(current_user: dict = Depends(get_current_user)):
    """Get all plants in your collection."""
    return await PlantService.get_user_plants(current_user["id"])


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
    return await PlantService.get_plant_by_id(plant_id, current_user["id"])


@router.patch("/{plant_id}", response_model=PlantResponse)
async def update_plant(
    plant_id: str,
    updates: PlantUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a plant in your collection (health_status, notes, image_url)."""
    return await PlantService.update_plant(
        plant_id, 
        current_user["id"], 
        updates.model_dump(exclude_none=True)
    )


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
        
        return HealthTimelineResponse(
            plant_id=plant_id,
            snapshots=[
                HealthSnapshot(
                    id=str(s["_id"]),
                    plant_id=s["plant_id"],
                    health_status=s["health_status"],
                    confidence=s.get("confidence", 0.0),
                    issues=s.get("issues", []),
                    image_url=s.get("image_url"),
                    created_at=s["created_at"]
                )
                for s in snapshots
            ],
            total_count=total
        )
    except Exception as e:
        raise AppException(f"Failed to get health timeline: {str(e)}")
