"""Care Club guards (privacy/visibility enforcement)."""

from datetime import datetime, timedelta
from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import ForbiddenException, TooManyRequestsException
from app.core.config import get_settings


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


async def require_rate_limit(user_id: str, kind: str) -> None:
    """
    Simple Mongo-backed rate limiter (MOD-001).

    kind: "post" | "comment" | "helpful_vote"
    """
    settings = get_settings()
    now = datetime.utcnow()
    window_start = now - timedelta(hours=24)

    if kind == "post":
        limit = int(settings.CARE_CLUB_POSTS_PER_24H)
        collection = Database.get_collection("care_club_posts")
        query = {"author_id": user_id, "created_at": {"$gte": window_start}}
    elif kind == "comment":
        limit = int(settings.CARE_CLUB_COMMENTS_PER_24H)
        collection = Database.get_collection("care_club_comments")
        query = {"author_id": user_id, "created_at": {"$gte": window_start}}
    elif kind == "helpful_vote":
        limit = int(settings.CARE_CLUB_HELPFUL_VOTES_PER_24H)
        collection = Database.get_collection("care_club_helpful_votes")
        query = {"user_id": user_id, "created_at": {"$gte": window_start}}
    else:
        return

    try:
        count = await collection.count_documents(query)
        if count >= limit:
            raise TooManyRequestsException("You’re doing that too often. Please try again later.")
    except TooManyRequestsException:
        raise
    except Exception:
        # Fail open for rate limits to avoid blocking core usage on transient DB errors.
        return
