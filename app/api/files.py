"""Files API routes."""

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.core.dependencies import get_current_user
from app.core.aws import S3Service

router = APIRouter(prefix="/files", tags=["Files"])

class UploadUrlRequest(BaseModel):
    filename: str
    content_type: str = "image/jpeg"
    plant_id: str = "temp"  # Will be moved/renamed later ideally, or just organise by temp first

class UploadUrlResponse(BaseModel):
    upload_url: str
    file_key: str
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
    
    # Create a unique file path: uploads/users/{user_id}/{plant_id}/{timestamp}_{filename}
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    clean_filename = request.filename.replace(" ", "_")
    
    # Ensure extension matches content type (basic check)
    if "image" in request.content_type and not any(ext in clean_filename.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".heic"]):
        clean_filename += ".jpg"
        
    file_key = f"uploads/users/{current_user['id']}/{request.plant_id}/{timestamp}_{str(uuid.uuid4())[:8]}_{clean_filename}"
    
    try:
        url = s3_service.generate_presigned_put_url(
            object_name=file_key,
            file_type=request.content_type
        )
        
        return UploadUrlResponse(
            upload_url=url,
            file_key=file_key
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
