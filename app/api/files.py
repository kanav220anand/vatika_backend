"""Files API routes."""

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.core.dependencies import get_current_user
from app.core.aws import S3Service
from app.core.config import get_settings
from app.core.assets import public_asset_url

router = APIRouter(prefix="/files", tags=["Files"])

class UploadUrlRequest(BaseModel):
    filename: str
    content_type: str = "image/jpeg"
    plant_id: str = "new"  # Use 'new' for first upload, actual plant_id for subsequent
    folder_type: str = "default"  # 'default' for plant images, 'posts_images' for Care Club posts

class AvatarUploadRequest(BaseModel):
    filename: str
    content_type: str = "image/jpeg"

class UploadUrlResponse(BaseModel):
    upload_url: str
    file_key: str
    public_url: str  # Read URL to access the uploaded file (public base URL if set, else presigned GET)
    expires_in: int = 300

@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    request: UploadUrlRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a presigned URL to upload a file directly to S3.
    User uploads to this URL using PUT method.
    """
    s3_service = S3Service()
    
    # Create a unique file path: plants/{user_id}/{plant_id}/{timestamp}_{filename}
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    clean_filename = request.filename.replace(" ", "_")
    
    # Ensure extension matches content type (basic check)
    if "image" in request.content_type and not any(ext in clean_filename.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".heic"]):
        clean_filename += ".jpg"
    
    # Use cleaner path: plants/{user_id}/{plant_id}/... or plants/{user_id}/{plant_id}/posts_images/...
    if request.folder_type == "posts_images":
        file_key = f"plants/{current_user['id']}/{request.plant_id}/posts_images/{timestamp}_{str(uuid.uuid4())[:8]}_{clean_filename}"
    else:
        file_key = f"plants/{current_user['id']}/{request.plant_id}/{timestamp}_{str(uuid.uuid4())[:8]}_{clean_filename}"
    
    try:
        url = s3_service.generate_presigned_put_url(
            object_name=file_key,
            file_type=request.content_type
        )

        # Provide a read URL that actually works.
        # - For user uploads (plants/...): always presign (bucket is typically private)
        # - For static assets: use S3_BASE_URL if configured
        settings = get_settings()
        if file_key.startswith("plants/") or file_key.startswith("uploads/"):
            public_url = s3_service.generate_presigned_get_url(file_key, expiration=3600)
        elif (settings.S3_BASE_URL or "").strip():
            public_url = public_asset_url(file_key) or file_key
        else:
            # Best-effort fallback
            public_url = file_key
        
        return UploadUrlResponse(
            upload_url=url,
            file_key=file_key,
            public_url=public_url
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/avatar-upload-url", response_model=UploadUrlResponse)
async def get_avatar_upload_url(
    request: AvatarUploadRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a presigned URL to upload a profile avatar directly to S3.
    
    Avatar is stored at: avatars/{user_id}/{timestamp}_{filename}
    Returns upload_url (PUT) and public_url (presigned GET for reading).
    """
    s3_service = S3Service()
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    clean_filename = request.filename.replace(" ", "_")
    
    # Ensure extension matches content type
    if "image" in request.content_type and not any(ext in clean_filename.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".heic"]):
        clean_filename += ".jpg"
    
    # Store avatars in a dedicated folder: avatars/{user_id}/...
    file_key = f"avatars/{current_user['id']}/{timestamp}_{str(uuid.uuid4())[:8]}_{clean_filename}"
    
    try:
        upload_url = s3_service.generate_presigned_put_url(
            object_name=file_key,
            file_type=request.content_type
        )
        
        # Generate a presigned GET URL for reading (avatars are private)
        public_url = s3_service.generate_presigned_get_url(file_key, expiration=86400 * 7)  # 7 days
        
        return UploadUrlResponse(
            upload_url=upload_url,
            file_key=file_key,
            public_url=public_url
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/avatar-url")
async def get_avatar_url(
    file_key: str = Query(..., description="S3 key of the avatar"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get a fresh presigned URL for an existing avatar.
    
    Use this to refresh expired avatar URLs.
    """
    s3_service = S3Service()
    
    # Security: Only allow accessing avatars (not other files)
    if not file_key.startswith("avatars/"):
        raise HTTPException(status_code=400, detail="Invalid file key")
    
    try:
        public_url = s3_service.generate_presigned_get_url(file_key, expiration=86400 * 7)  # 7 days
        return {"url": public_url, "file_key": file_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
