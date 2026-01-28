"""User and authentication models."""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr, Field

# Auth provider types
AuthProvider = Literal["email", "google", "apple"]

# Onboarding status types
OnboardingStatus = Literal["never_shown", "shown", "skipped", "finished"]


class UserCreate(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=2)
    city: Optional[str] = None
    balcony_orientation: Optional[str] = Field(
        None, 
        pattern="^(north|south|east|west|north-east|north-west|south-east|south-west)$"
    )


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    """Schema for Google OAuth login/signup."""
    id_token: str = Field(..., description="Google ID token from frontend")


class UserLevelSummary(BaseModel):
    """Minimal level info attached to a user profile."""
    level: int
    title: str
    icon: str
    color: str
    badge_image_url: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for user response (excludes password)."""
    id: str
    email: str
    name: str
    city: Optional[str] = None
    balcony_orientation: Optional[str] = None
    auth_provider: str = "email"  # "email" | "google" | "apple"
    profile_picture: Optional[str] = None  # S3 key
    profile_picture_url: Optional[str] = None  # Presigned URL for display
    notifications_enabled: bool = True
    profile_visibility: str = Field(default="public", pattern="^(public|private)$")
    onboarding_status: str = "never_shown"  # never_shown | shown | skipped | finished
    total_achievement_score: int = 0
    level: int = 1
    title: str = "Seed"
    user_level: Optional[UserLevelSummary] = None
    created_at: datetime


class UserUpdate(BaseModel):
    """Schema for user profile update."""
    name: Optional[str] = None
    city: Optional[str] = None
    balcony_orientation: Optional[str] = Field(
        None,
        pattern="^(north|south|east|west|north-east|north-west|south-east|south-west)$"
    )
    profile_picture: Optional[str] = None  # S3 key or URL for avatar
    notifications_enabled: Optional[bool] = None
    profile_visibility: Optional[str] = Field(default=None, pattern="^(public|private)$")
    onboarding_status: Optional[str] = Field(
        None,
        pattern="^(never_shown|shown|skipped|finished)$"
    )


class TokenResponse(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    is_new_user: bool = False  # True if user just signed up


class ForgotPasswordRequest(BaseModel):
    """Schema for requesting password reset."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Schema for resetting password with token."""
    token: str = Field(..., min_length=32, description="Password reset token from email")
    new_password: str = Field(..., min_length=6, description="New password (min 6 characters)")


class VerifyResetTokenResponse(BaseModel):
    """Schema for token verification response."""
    valid: bool
    email: Optional[str] = None  # Only returned if token is valid
    error: Optional[str] = None  # Only returned if token is invalid


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str

