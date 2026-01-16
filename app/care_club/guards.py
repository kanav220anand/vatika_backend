"""Care Club guards (privacy/visibility enforcement)."""

from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import ForbiddenException


PRIVATE_CARE_CLUB_MESSAGE = "Your profile is private. Switch to Public to participate in Care Club."


async def require_public_profile(user_id: str) -> None:
    """
    Enforce that a user has a public profile to perform Care Club write actions.

    Reads are allowed for everyone; writes are blocked for private profiles.
    """
    try:
        user = await Database.get_collection("users").find_one(
            {"_id": ObjectId(user_id)},
            {"profile_visibility": 1},
        )
        if not user:
            raise ForbiddenException(PRIVATE_CARE_CLUB_MESSAGE)
        if (user.get("profile_visibility") or "public") == "private":
            raise ForbiddenException(PRIVATE_CARE_CLUB_MESSAGE)
    except ForbiddenException:
        raise
    except Exception:
        # Fail closed for privacy/safety.
        raise ForbiddenException(PRIVATE_CARE_CLUB_MESSAGE)

