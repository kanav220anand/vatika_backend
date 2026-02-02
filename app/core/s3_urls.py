"""
Helpers to resolve user-uploaded S3 keys into presigned URLs.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from app.core.aws import S3Service
from app.core.config import get_settings
from app.core.s3_keys import normalize_s3_key


def presign_user_upload(value: Optional[str], *, expiration: int = 3600) -> Optional[str]:
    """
    Convert user-uploaded S3 keys (or older stored S3 URLs) into a fresh presigned URL.

    - If the value is already a non-S3 URL (e.g. Unsplash), return as-is.
    - If the value maps to a user-uploaded key (plants/uploads/avatars), presign it.
    - Otherwise, return the original value unchanged.
    """
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    settings = get_settings()
    key = normalize_s3_key(raw, bucket=settings.AWS_S3_BUCKET, region=settings.AWS_REGION)

    if key and (key.startswith("plants/") or key.startswith("uploads/") or key.startswith("avatars/")):
        try:
            return S3Service().generate_presigned_get_url(key, expiration=expiration)
        except Exception:
            return raw

    return raw


def presign_user_uploads(values: Iterable[str], *, expiration: int = 3600) -> List[str]:
    """Presign a list of user-uploaded keys/URLs; omits empty values."""
    out: List[str] = []
    for value in values:
        resolved = presign_user_upload(value, expiration=expiration)
        if resolved:
            out.append(resolved)
    return out
