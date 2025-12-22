"""Authentication module - JWT auth, user management."""

from app.auth.views import router as auth_router

__all__ = ["auth_router"]
