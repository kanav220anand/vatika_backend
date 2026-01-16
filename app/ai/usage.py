"""Usage logging for AI endpoints (COST-001)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any, Dict

from app.core.database import Database


@dataclass(frozen=True)
class AIUsageLog:
    user_id: str
    endpoint: str
    model: str
    status: str  # success|fail
    latency_ms: int
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    estimated_cost: Optional[float] = None
    error_type: Optional[str] = None


class AIUsageService:
    @staticmethod
    def _collection():
        return Database.get_collection("ai_usage")

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    @classmethod
    async def log(cls, entry: AIUsageLog, extra: Optional[Dict[str, Any]] = None) -> None:
        doc = {
            "user_id": entry.user_id,
            "endpoint": entry.endpoint,
            "model": entry.model,
            "status": entry.status,
            "latency_ms": int(entry.latency_ms),
            "tokens_in": entry.tokens_in,
            "tokens_out": entry.tokens_out,
            "estimated_cost": entry.estimated_cost,
            "error_type": entry.error_type,
            "created_at": cls._now(),
        }
        if extra:
            # Do not store raw prompts/images; keep extra metadata minimal.
            doc["extra"] = extra
        try:
            await cls._collection().insert_one(doc)
        except Exception:
            # Logging must never break production flows.
            return

