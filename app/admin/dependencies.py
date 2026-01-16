from fastapi import Header

from app.core.config import get_settings
from app.core.exceptions import ForbiddenException


def require_admin_api_key(x_admin_api_key: str = Header(default="", alias="X-ADMIN-API-KEY")) -> str:
    """
    MVP admin auth via API key header.

    If ADMIN_API_KEY is not configured, deny all admin access (fail closed).
    """
    settings = get_settings()
    expected = (settings.ADMIN_API_KEY or "").strip()
    provided = (x_admin_api_key or "").strip()

    if not expected or provided != expected:
        raise ForbiddenException("Admin access denied")
    return "admin_api_key"

