"""AWS S3 Service."""

import logging
import re
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

    @staticmethod
    def _validated_bucket_name() -> str:
        bucket = (settings.AWS_S3_BUCKET or "").strip()
        # Prevent boto3 raising a cryptic "Invalid bucket name" error when env is misconfigured.
        if not bucket:
            raise ValueError("AWS_S3_BUCKET is not configured.")
        # https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError(f"Invalid AWS_S3_BUCKET value '{bucket}'.")
        return bucket

    def generate_presigned_post(self, object_name: str, file_type: str, expiration=3600):
        """
        Generate a presigned URL/fields for POST upload.
        
        Note: For simple PUT uploads (which are easier for frontend to track progress),
        generate_presigned_url('put_object') is often preferred.
        """
        if not self.client:
            raise ValueError("AWS S3 credentials not configured.")

        try:
            bucket = self._validated_bucket_name()
            response = self.client.generate_presigned_post(
                Bucket=bucket,
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
            bucket = self._validated_bucket_name()
            url = self.client.generate_presigned_url(
                ClientMethod='put_object',
                Params={
                    'Bucket': bucket,
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
            bucket = self._validated_bucket_name()
            url = self.client.generate_presigned_url(
                ClientMethod='get_object',
                Params={
                    'Bucket': bucket,
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
            # COST-001: avoid downloading arbitrarily large objects into memory.
            try:
                bucket = self._validated_bucket_name()
                head = self.client.head_object(Bucket=bucket, Key=object_name)
                max_bytes = int(getattr(settings, "AI_MAX_S3_IMAGE_BYTES", 8_000_000))
                size = int(head.get("ContentLength") or 0)
                if size and size > max_bytes:
                    raise ValueError("Image is too large to analyze. Please upload a smaller photo.")
            except ValueError:
                raise
            except Exception:
                # If HEAD fails, proceed (best-effort) – downstream limits still apply.
                bucket = self._validated_bucket_name()

            file_stream = BytesIO()
            self.client.download_fileobj(bucket, object_name, file_stream)
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
        bucket = self._validated_bucket_name()
        return f"https://{bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{object_name}"

    def upload_bytes(self, object_name: str, data: bytes, content_type: str = "image/jpeg") -> None:
        """Upload raw bytes to S3."""
        if not self.client:
            raise ValueError("AWS S3 credentials not configured.")
        try:
            bucket = self._validated_bucket_name()
            self.client.put_object(
                Bucket=bucket,
                Key=object_name,
                Body=data,
                ContentType=content_type,
            )
        except ClientError as e:
            logger.error(f"Error uploading file to S3: {e}")
            raise

    def delete_object(self, object_name: str) -> None:
        """Delete an object from S3."""
        if not self.client:
            raise ValueError("AWS S3 credentials not configured.")
        try:
            bucket = self._validated_bucket_name()
            self.client.delete_object(
                Bucket=bucket,
                Key=object_name,
            )
        except ClientError as e:
            logger.error(f"Error deleting file from S3: {e}")
            raise
