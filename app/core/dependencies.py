"""
Common dependencies for FastAPI routes.
"""

from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# HTTP Bearer token security scheme
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


def _decode_token(token: str) -> Optional[dict]:
    """Decode JWT token. Import here to avoid circular imports."""
    from app.auth.service import AuthService
    return AuthService.decode_token(token)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Dependency to get the current authenticated user from JWT token.
    Returns user dict with 'id' and 'email'.
    """
    payload = _decode_token(credentials.credentials)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {
        "id": payload["sub"],
        "email": payload["email"],
    }


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional)
) -> Optional[dict]:
    """
    Optional authentication - returns user if token is valid, None otherwise.
    """
    if not credentials:
        return None
    
    payload = _decode_token(credentials.credentials)
    if not payload:
        return None
    
    return {
        "id": payload["sub"],
        "email": payload["email"],
    }

