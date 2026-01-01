"""AWS S3 Service."""

import logging
import boto3
from botocore.exceptions import ClientError
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class S3Service:
    """Handles S3 interactions."""

    _instance = None
    _s3_client = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            try:
                cls._instance._s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_REGION,
                    config=boto3.session.Config(s3={'addressing_style': 'path'})
                )
            except Exception as e:
                logger.error(f"Failed to initialize S3 client: {e}")
                cls._instance._s3_client = None
        return cls._instance

    @property
    def client(self):
        """Get S3 client."""
        return self._s3_client

    def generate_presigned_post(self, object_name: str, file_type: str, expiration=3600):
        """
        Generate a presigned URL/fields for POST upload.
        
        Note: For simple PUT uploads (which are easier for frontend to track progress),
        generate_presigned_url('put_object') is often preferred.
        """
        if not self.client:
            raise ValueError("AWS S3 credentials not configured.")

        try:
            response = self.client.generate_presigned_post(
                Bucket=settings.AWS_S3_BUCKET,
                Key=object_name,
                Fields={"Content-Type": file_type},
                Conditions=[
                    {"Content-Type": file_type},
                    ["content-length-range", 0, 52428800]  # Max 50MB
                ],
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            logger.error(f"Error generating presigned POST: {e}")
            raise

    def generate_presigned_put_url(self, object_name: str, file_type: str, expiration=300):
        """
        Generate a presigned URL for PUT upload.
        This is often easier for frontends using axios/fetch with progress tracking.
        """
        if not self.client:
            raise ValueError("AWS S3 credentials not configured.")

        try:
            url = self.client.generate_presigned_url(
                ClientMethod='put_object',
                Params={
                    'Bucket': settings.AWS_S3_BUCKET,
                    'Key': object_name,
                    'ContentType': file_type
                },
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned PUT URL: {e}")
            raise

    def generate_presigned_get_url(self, object_name: str, expiration=300):
        """Generate a presigned URL for reading private objects."""
        if not self.client:
            raise ValueError("AWS S3 credentials not configured.")

        try:
            url = self.client.generate_presigned_url(
                ClientMethod='get_object',
                Params={
                    'Bucket': settings.AWS_S3_BUCKET,
                    'Key': object_name
                },
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned GET URL: {e}")
            raise

    def download_file_as_base64(self, object_name: str) -> str:
        """
        Download a file from S3 and return it as a base64 string.
        Performed in-memory, no file is written to disk.
        """
        import base64
        from io import BytesIO

        if not self.client:
            raise ValueError("AWS S3 credentials not configured.")

        try:
            file_stream = BytesIO()
            self.client.download_fileobj(settings.AWS_S3_BUCKET, object_name, file_stream)
            file_stream.seek(0)
            return base64.b64encode(file_stream.read()).decode('utf-8')
        except ClientError as e:
            logger.error(f"Error downloading file from S3: {e}")
            raise

    def get_public_url(self, object_name: str) -> str:
        """
        Get the public URL for an S3 object.
        Assumes bucket has public read access or CloudFront is configured.
        """
        return f"https://{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{object_name}"
