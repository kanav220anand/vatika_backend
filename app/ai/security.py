"""Security helpers for AI endpoints (COST-001)."""

import re
from typing import Optional

from app.core.exceptions import BadRequestException, ForbiddenException


_DISALLOWED_KEY_PATTERN = re.compile(r"(^/)|(\.\.)|(\x00)")


def validate_user_owned_s3_key(user_id: str, key: str, *, allowed_prefixes: Optional[list[str]] = None) -> str:
    """
    Validate that `key` is a safe-looking S3 object key and belongs to the current user.

    COST-001/SEC-002 requirement: prevent analyzing arbitrary S3 keys.
    """
    if not isinstance(key, str) or not key.strip():
        raise BadRequestException("image_key is required")

    normalized = key.strip()
    if normalized.startswith("http://") or normalized.startswith("https://"):
        raise BadRequestException("Use an S3 object key (image_key), not a URL.")

    if _DISALLOWED_KEY_PATTERN.search(normalized):
        raise BadRequestException("Invalid image_key.")

    prefixes = allowed_prefixes or [f"plants/{user_id}/", f"uploads/{user_id}/"]
    if not any(normalized.startswith(p) for p in prefixes):
        raise ForbiddenException("You can only analyze your own uploaded images.")

    # Hard cap to avoid abusive keys.
    if len(normalized) > 512:
        raise BadRequestException("image_key is too long.")

    return normalized


def validate_base64_payload(b64: Optional[str], *, max_chars: int, field_name: str) -> None:
    """
    Best-effort guard for legacy base64 fields.

    We prefer S3 keys, but some endpoints still support thumbnails as base64.
    """
    if not b64:
        return
    if not isinstance(b64, str):
        raise BadRequestException(f"Invalid {field_name}.")
    if len(b64) > max_chars:
        raise BadRequestException(f"{field_name} is too large. Upload to S3 and send image_key instead.")

