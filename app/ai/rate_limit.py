"""Mongo-based rate limiting and daily quotas (COST-001)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from pymongo import ReturnDocument

from app.core.config import get_settings
from app.core.database import Database
from app.core.exceptions import AppException


class RateLimitExceeded(AppException):
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=429)


@dataclass(frozen=True)
class RateLimitResult:
    count: int
    limit: int
    reset_seconds: int


class RateLimitService:
    @staticmethod
    def _collection():
        return Database.get_collection("rate_limits")

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _window_start(cls, now: datetime, window_seconds: int) -> datetime:
        epoch = int(now.timestamp())
        start_epoch = (epoch // window_seconds) * window_seconds
        return datetime.fromtimestamp(start_epoch, tz=timezone.utc)

    @classmethod
    async def hit(cls, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = cls._now()
        window_start = cls._window_start(now, window_seconds)
        window_end = window_start + timedelta(seconds=window_seconds)
        reset_seconds = max(0, int((window_end - now).total_seconds()))

        doc_id = f"{key}:{int(window_start.timestamp())}"
        expires_at = window_end + timedelta(minutes=5)  # small buffer for TTL cleanup

        doc = await cls._collection().find_one_and_update(
            {"_id": doc_id},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {
                    "_id": doc_id,
                    "key": key,
                    "window_start": window_start,
                    "expires_at": expires_at,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        count = int((doc or {}).get("count", 0))
        if count > int(limit):
            raise RateLimitExceeded(f"Rate limit exceeded. Try again in {reset_seconds} seconds.")

        return RateLimitResult(count=count, limit=int(limit), reset_seconds=reset_seconds)

    @classmethod
    async def hit_daily(cls, key: str, *, limit: int) -> RateLimitResult:
        now = cls._now()
        day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        reset_seconds = max(0, int((day_end - now).total_seconds()))
        doc_id = f"{key}:{day_start.date().isoformat()}"
        expires_at = day_end + timedelta(days=2)

        doc = await cls._collection().find_one_and_update(
            {"_id": doc_id},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {
                    "_id": doc_id,
                    "key": key,
                    "window_start": day_start,
                    "expires_at": expires_at,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        count = int((doc or {}).get("count", 0))
        if count > int(limit):
            raise RateLimitExceeded("Daily limit reached. Try again tomorrow.")

        return RateLimitResult(count=count, limit=int(limit), reset_seconds=reset_seconds)


async def enforce_ai_limits(
    *,
    request: Request,
    user_id: str,
    endpoint: str,
    per_minute: int,
    daily_requests: int,
    daily_snapshots: Optional[int] = None,
) -> None:
    """
    Enforce per-user + per-IP rate limits and daily quotas for AI endpoints.
    """
    settings = get_settings()

    ip = (request.client.host if request.client else "").strip() or "unknown"
    await RateLimitService.hit(
        f"ip:{ip}:ai",
        limit=int(settings.AI_RATE_PER_IP_PER_MINUTE),
        window_seconds=60,
    )

    await RateLimitService.hit(
        f"user:{user_id}:{endpoint}",
        limit=int(per_minute),
        window_seconds=60,
    )

    await RateLimitService.hit_daily(f"user:{user_id}:ai_requests", limit=int(daily_requests))

    if daily_snapshots is not None:
        await RateLimitService.hit_daily(f"user:{user_id}:ai_snapshots", limit=int(daily_snapshots))

