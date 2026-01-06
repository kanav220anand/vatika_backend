"""Helpers for building public asset URLs."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

from app.core.config import get_settings


def public_asset_url(path: Optional[str]) -> Optional[str]:
    """
    Build a public URL for an asset path stored in the DB.

    - If `path` is already an absolute URL, returns it unchanged.
    - If `S3_BASE_URL` is unset, returns `path` unchanged.
    - Otherwise, joins `S3_BASE_URL` (expected trailing slash) with the path.
    """
    if not path:
        return None

    value = path.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value

    settings = get_settings()
    base = (settings.S3_BASE_URL or "").strip()
    if not base:
        return value.lstrip("/")

    if not base.endswith("/"):
        base = base + "/"

    return urljoin(base, value.lstrip("/"))

