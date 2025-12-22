"""Video processing service for multi-plant detection.

Handles extraction of frames from video files (MP4, MOV, WebM, AVI)
for plant analysis.
"""

import base64
import io
import tempfile
from typing import Optional, List, Tuple
from PIL import Image

# Maximum file size: 50MB
MAX_VIDEO_SIZE_MB = 50
MAX_VIDEO_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024

# Supported video MIME types
SUPPORTED_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-msvideo": ".avi",
}


class VideoProcessingError(Exception):
    """Raised when video processing fails."""
    pass


class VideoService:
    """Handles video processing for plant detection."""

    @staticmethod
    def validate_video(video_base64: str, mime_type: str) -> bytes:
        """
        Validate video file size and format.
        
        Args:
            video_base64: Base64 encoded video data
            mime_type: MIME type of the video
            
        Returns:
            Decoded video bytes
            
        Raises:
            VideoProcessingError: If validation fails
        """
        if mime_type not in SUPPORTED_VIDEO_TYPES:
            raise VideoProcessingError(
                f"Unsupported video format: {mime_type}. "
                f"Supported formats: {', '.join(SUPPORTED_VIDEO_TYPES.keys())}"
            )
        
        try:
            video_bytes = base64.b64decode(video_base64)
        except Exception as e:
            raise VideoProcessingError(f"Invalid base64 encoding: {e}")
        
        if len(video_bytes) > MAX_VIDEO_SIZE_BYTES:
            raise VideoProcessingError(
                f"Video file too large. Maximum size is {MAX_VIDEO_SIZE_MB}MB, "
                f"but file is {len(video_bytes) / 1024 / 1024:.1f}MB"
            )
        
        return video_bytes

    @staticmethod
    def extract_representative_frame(
        video_base64: str, 
        mime_type: str
    ) -> str:
        """
        Extract a single representative frame from the video.
        
        For plant detection, we extract a frame from the middle of the video
        as it's most likely to have stable, clear content.
        
        Args:
            video_base64: Base64 encoded video data
            mime_type: MIME type of the video
            
        Returns:
            Base64 encoded image (JPEG)
        """
        video_bytes = VideoService.validate_video(video_base64, mime_type)
        
        try:
            # Import moviepy here to avoid startup overhead if not used
            from moviepy.editor import VideoFileClip
        except ImportError:
            raise VideoProcessingError(
                "Video processing requires 'moviepy' package. "
                "Install with: pip install moviepy"
            )
        
        # Write to temp file (moviepy requires file path)
        extension = SUPPORTED_VIDEO_TYPES[mime_type]
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        
        try:
            clip = VideoFileClip(tmp_path)
            
            # Get frame from middle of video
            frame_time = clip.duration / 2
            frame = clip.get_frame(frame_time)
            
            # Convert numpy array to PIL Image
            image = Image.fromarray(frame)
            
            # Convert to base64 JPEG
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
            buffer.seek(0)
            frame_base64 = base64.b64encode(buffer.read()).decode("utf-8")
            
            clip.close()
            
            return frame_base64
            
        except Exception as e:
            raise VideoProcessingError(f"Failed to extract frame from video: {e}")
        finally:
            # Clean up temp file
            import os
            try:
                os.unlink(tmp_path)
            except:
                pass

    @staticmethod
    def extract_keyframes(
        video_base64: str, 
        mime_type: str,
        max_frames: int = 5
    ) -> List[str]:
        """
        Extract multiple keyframes from the video for comprehensive analysis.
        
        Args:
            video_base64: Base64 encoded video data
            mime_type: MIME type of the video
            max_frames: Maximum number of frames to extract
            
        Returns:
            List of base64 encoded images (JPEG)
        """
        video_bytes = VideoService.validate_video(video_base64, mime_type)
        
        try:
            from moviepy.editor import VideoFileClip
        except ImportError:
            raise VideoProcessingError(
                "Video processing requires 'moviepy' package. "
                "Install with: pip install moviepy"
            )
        
        extension = SUPPORTED_VIDEO_TYPES[mime_type]
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        
        frames_base64 = []
        
        try:
            clip = VideoFileClip(tmp_path)
            
            # Calculate frame times (evenly distributed)
            duration = clip.duration
            if duration < 1:
                # Very short video, just get one frame
                times = [duration / 2]
            else:
                # Exclude first and last 10% to avoid black frames
                start = duration * 0.1
                end = duration * 0.9
                step = (end - start) / (max_frames - 1) if max_frames > 1 else 0
                times = [start + i * step for i in range(max_frames)]
            
            for frame_time in times:
                frame = clip.get_frame(frame_time)
                image = Image.fromarray(frame)
                
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=85)
                buffer.seek(0)
                frames_base64.append(base64.b64encode(buffer.read()).decode("utf-8"))
            
            clip.close()
            
            return frames_base64
            
        except Exception as e:
            raise VideoProcessingError(f"Failed to extract frames from video: {e}")
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except:
                pass


class ImageService:
    """Handles image processing for plant detection."""

    @staticmethod
    def crop_plant_thumbnail(
        image_base64: str,
        bbox: dict,
        padding: float = 0.10
    ) -> str:
        """
        Crop a plant region from an image based on bounding box.
        
        Args:
            image_base64: Base64 encoded image
            bbox: Bounding box dict with x, y, width, height (normalized 0-1)
            padding: Extra padding around the crop (as fraction)
            
        Returns:
            Base64 encoded cropped image (JPEG)
        """
        try:
            image_bytes = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            raise ValueError(f"Invalid image data: {e}")
        
        img_width, img_height = image.size
        
        # Convert normalized coords to pixels
        x = bbox["x"] * img_width
        y = bbox["y"] * img_height
        w = bbox["width"] * img_width
        h = bbox["height"] * img_height
        
        # Add padding
        pad_x = w * padding
        pad_y = h * padding
        
        left = max(0, x - pad_x)
        top = max(0, y - pad_y)
        right = min(img_width, x + w + pad_x)
        bottom = min(img_height, y + h + pad_y)
        
        # Crop
        cropped = image.crop((int(left), int(top), int(right), int(bottom)))
        
        # Convert to base64
        buffer = io.BytesIO()
        cropped.save(buffer, format="JPEG", quality=90)
        buffer.seek(0)
        
        return base64.b64encode(buffer.read()).decode("utf-8")

    @staticmethod
    def create_thumbnail(
        image_base64: str,
        max_size: Tuple[int, int] = (384, 384)
    ) -> str:
        """
        Create a thumbnail from an image.
        
        Args:
            image_base64: Base64 encoded image
            max_size: Maximum thumbnail dimensions
            
        Returns:
            Base64 encoded thumbnail (JPEG)
        """
        try:
            image_bytes = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            raise ValueError(f"Invalid image data: {e}")
        
        # Convert RGBA to RGB if needed
        if image.mode == "RGBA":
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
        
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)
        
        return base64.b64encode(buffer.read()).decode("utf-8")
