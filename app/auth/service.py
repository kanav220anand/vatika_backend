"""Authentication service - JWT handling, password hashing, user operations."""

from datetime import datetime, timedelta
from typing import Optional, Tuple
import jwt
from passlib.context import CryptContext
from bson import ObjectId
from google.oauth2 import id_token
from google.auth.transport import requests

from app.core.config import get_settings
from app.core.database import Database
from app.core.exceptions import BadRequestException, UnauthorizedException, NotFoundException
from app.auth.models import UserCreate, UserResponse, TokenResponse, UserLevelSummary
from app.achievements.service import AchievementService

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Handles authentication and user operations."""
    
    # ==================== Profile Helpers ====================

    @classmethod
    async def _get_user_level_summary(cls, points: int) -> UserLevelSummary:
        """Get minimal level info for a user, including expanded badge URL."""
        from app.gamification.service import GamificationService

        level_doc = await GamificationService.get_level_for_points(points)
        if not level_doc:
            levels = await GamificationService.get_all_levels(use_cache=True)
            level_doc = levels[0].model_dump() if levels else {}

        return UserLevelSummary(
            level=level_doc.get("level", 1),
            title=level_doc.get("title", "Seed"),
            icon=level_doc.get("icon", "🫘"),
            color=level_doc.get("color", "#8B5A2B"),
            badge_image_url=level_doc.get("badge_image_url"),
        )

    @classmethod
    async def _build_user_response(cls, user: dict) -> UserResponse:
        """Build a consistent UserResponse from a DB user document."""
        points = user.get("total_achievement_score", 0)
        user_level = await cls._get_user_level_summary(points)

        return UserResponse(
            id=str(user["_id"]),
            email=user["email"],
            name=user["name"],
            city=user.get("city"),
            balcony_orientation=user.get("balcony_orientation"),
            auth_provider=user.get("auth_provider", "email"),
            profile_picture=user.get("profile_picture"),
            notifications_enabled=bool(user.get("notifications_enabled", True)),
            profile_visibility=user.get("profile_visibility", "public"),
            onboarding_status=user.get("onboarding_status", "never_shown"),
            total_achievement_score=points,
            level=user_level.level,
            title=user_level.title,
            user_level=user_level,
            created_at=user["created_at"],
        )

    @classmethod
    async def add_score(cls, user_id: str, score: int) -> int:
        """Add score to user's total_achievement_score and return new total."""
        users = cls._get_collection()
        
        result = await users.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$inc": {"total_achievement_score": score}},
            return_document=True
        )
        
        return result.get("total_achievement_score", 0) if result else 0

    # ==================== Password & Token ====================
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt."""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def create_access_token(user_id: str, email: str) -> str:
        """Create a JWT access token."""
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": user_id,
            "email": email,
            "exp": expire,
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    
    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        """Decode and validate a JWT token."""
        try:
            payload = jwt.decode(
                token, 
                settings.JWT_SECRET_KEY, 
                algorithms=[settings.JWT_ALGORITHM]
            )
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    # ==================== Google OAuth ====================
    
    @classmethod
    async def verify_google_token(cls, token: str) -> dict:
        """
        Verify Google ID token and extract user info.
        Returns: { email, name, picture, google_id }
        """
        try:
            # Verify the token with Google
            idinfo = id_token.verify_oauth2_token(
                token,
                requests.Request(),
                settings.GOOGLE_CLIENT_ID
            )
            
            # Verify issuer
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                raise UnauthorizedException("Invalid token issuer")
            
            return {
                "email": idinfo.get("email"),
                "name": idinfo.get("name", idinfo.get("email", "").split("@")[0]),
                "picture": idinfo.get("picture"),
                "google_id": idinfo.get("sub"),
            }
        except ValueError as e:
            raise UnauthorizedException(f"Invalid Google token: {str(e)}")
    
    @classmethod
    async def google_auth(cls, id_token_str: str) -> Tuple[TokenResponse, bool]:
        """
        Authenticate via Google OAuth.
        Returns (TokenResponse, is_new_user)
        """
        # Verify Google token
        google_user = await cls.verify_google_token(id_token_str)
        
        users = cls._get_collection()
        
        # Check if user exists
        existing_user = await users.find_one({"email": google_user["email"]})
        
        if existing_user:
            # Existing user - log them in
            user_id = str(existing_user["_id"])
            token = cls.create_access_token(user_id, existing_user["email"])
            
            # Update profile picture if changed
            if google_user.get("picture") and existing_user.get("profile_picture") != google_user["picture"]:
                await users.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": {"profile_picture": google_user["picture"]}}
                )
                existing_user["profile_picture"] = google_user["picture"]
            
            user_response = await cls._build_user_response(existing_user)
            
            return TokenResponse(access_token=token, user=user_response, is_new_user=False), False
        
        else:
            # New user - create account
            user_doc = {
                "email": google_user["email"],
                "password_hash": None,  # No password for OAuth users
                "name": google_user["name"],
                "city": None,  # Will be set when user uploads first plant
                "balcony_orientation": None,
                "auth_provider": "google",
                "google_id": google_user["google_id"],
                "profile_picture": google_user.get("picture"),
                "notifications_enabled": True,
                "profile_visibility": "public",
                "onboarding_status": "never_shown",
                "total_achievement_score": 5,  # Welcome bonus
                "created_at": datetime.utcnow(),
            }
            
            result = await users.insert_one(user_doc)
            user_id = str(result.inserted_id)
            
            # Auto-unlock early_adopter achievement for new signups
            await AchievementService.unlock_achievement(user_id, "early_adopter")
            
            token = cls.create_access_token(user_id, google_user["email"])

            # Fetch fresh user doc to include any score changes from achievements
            created = await users.find_one({"_id": ObjectId(user_id)})
            user_response = await cls._build_user_response(created)

            return TokenResponse(access_token=token, user=user_response, is_new_user=True), True
    
    # ==================== User Operations ====================
    
    @classmethod
    def _get_collection(cls):
        return Database.get_collection("users")
    
    @classmethod
    async def register(cls, user_data: UserCreate) -> TokenResponse:
        """Register a new user."""
        users = cls._get_collection()
        
        # Check if email exists
        existing = await users.find_one({"email": user_data.email})
        if existing:
            raise BadRequestException("Email already registered")
        
        # Create user document
        user_doc = {
            "email": user_data.email,
            "password_hash": cls.hash_password(user_data.password),
            "name": user_data.name,
            "city": user_data.city,
            "balcony_orientation": user_data.balcony_orientation,
            "auth_provider": "email",
            "notifications_enabled": True,
            "profile_visibility": "public",
            "onboarding_status": "never_shown",
            "total_achievement_score": 5,  # Welcome bonus
            "created_at": datetime.utcnow(),
        }
        
        result = await users.insert_one(user_doc)
        user_id = str(result.inserted_id)
        
        # Auto-unlock early_adopter achievement for new signups
        await AchievementService.unlock_achievement(user_id, "early_adopter")
        
        # Generate token
        token = cls.create_access_token(user_id, user_data.email)

        # Fetch fresh user doc to include any score changes from achievements
        created = await users.find_one({"_id": ObjectId(user_id)})
        user_response = await cls._build_user_response(created)

        return TokenResponse(access_token=token, user=user_response, is_new_user=True)
    
    @classmethod
    async def login(cls, email: str, password: str) -> TokenResponse:
        """Authenticate user and return token."""
        users = cls._get_collection()
        
        user = await users.find_one({"email": email})
        if not user:
            raise UnauthorizedException("Invalid email or password")
        
        # Check if user signed up via OAuth (no password)
        if not user.get("password_hash"):
            auth_provider = user.get("auth_provider", "unknown")
            raise UnauthorizedException(
                f"This account uses {auth_provider.title()} sign-in. Please use that method."
            )
        
        if not cls.verify_password(password, user["password_hash"]):
            raise UnauthorizedException("Invalid email or password")
        
        user_id = str(user["_id"])
        token = cls.create_access_token(user_id, user["email"])

        user_response = await cls._build_user_response(user)
        
        return TokenResponse(access_token=token, user=user_response)
    
    @classmethod
    async def get_user_by_id(cls, user_id: str) -> UserResponse:
        """Get user by ID."""
        users = cls._get_collection()
        
        user = await users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise NotFoundException("User not found")

        return await cls._build_user_response(user)
    
    @classmethod
    async def update_user(cls, user_id: str, updates: dict) -> UserResponse:
        """Update user profile."""
        users = cls._get_collection()
        
        # Only allow updating specific fields
        allowed_fields = {
            "name",
            "city",
            "balcony_orientation",
            "onboarding_status",
            "notifications_enabled",
            "profile_visibility",
        }
        filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields and v is not None}
        
        if filtered_updates:
            await users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": filtered_updates}
            )
        
        return await cls.get_user_by_id(user_id)
    
    @classmethod
    async def get_user_city(cls, user_id: str) -> Optional[str]:
        """Get user's city."""
        users = cls._get_collection()
        user = await users.find_one({"_id": ObjectId(user_id)}, {"city": 1})
        return user.get("city") if user else None
