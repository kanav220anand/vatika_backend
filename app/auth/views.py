"""Authentication API routes."""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.auth.models import (
    UserCreate, 
    UserLogin, 
    UserResponse, 
    UserUpdate, 
    TokenResponse,
    GoogleAuthRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    """
    Register a new user account with email/password.
    
    Returns access token and user info on success.
    """
    return await AuthService.register(user_data)


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """
    Login with email and password.
    
    Returns access token and user info on success.
    """
    return await AuthService.login(credentials.email, credentials.password)


@router.post("/google", response_model=TokenResponse)
async def google_auth(request: GoogleAuthRequest):
    """
    Authenticate with Google OAuth.
    
    Send the ID token received from Google Sign-In.
    - If user exists: logs them in
    - If new user: creates account with auth_provider="google"
    
    Returns access token and user info, plus is_new_user flag.
    """
    response, _ = await AuthService.google_auth(request.id_token)
    return response


@router.get("/me", response_model=UserResponse)
async def get_profile(current_user: dict = Depends(get_current_user)):
    """Get current user's profile."""
    return await AuthService.get_user_by_id(current_user["id"])


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    updates: UserUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update current user's profile.
    
    Updatable fields: name, city, balcony_orientation
    """
    return await AuthService.update_user(current_user["id"], updates.model_dump(exclude_none=True))


# ==================== Password Reset ====================

@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """
    Request a password reset email.
    
    Returns success message regardless of whether email exists (security measure).
    Email will contain a link to reset password (valid for 1 hour).
    
    Rate limited to 3 requests per email per hour.
    """
    from app.auth.models import MessageResponse
    result = await AuthService.request_password_reset(request.email)
    return MessageResponse(**result)


@router.get("/verify-reset-token")
async def verify_reset_token(token: str):
    """
    Verify if a password reset token is valid and not expired.
    
    Used by frontend to validate token before showing reset form.
    Returns user's email if valid, error message if invalid/expired.
    """
    from app.auth.models import VerifyResetTokenResponse
    result = await AuthService.verify_reset_token(token)
    return VerifyResetTokenResponse(**result)


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """
    Reset password using a valid token.
    
    Token is single-use and expires after 1 hour.
    Password must be at least 6 characters long.
    """
    from app.auth.models import MessageResponse
    result = await AuthService.reset_password(request.token, request.new_password)
    return MessageResponse(**result)


