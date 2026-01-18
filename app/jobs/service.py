"""Jobs service (API side, async) — JOBS-001."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId

from app.core.config import get_settings
from app.core.database import Database
from app.core.exceptions import BadRequestException, NotFoundException, ForbiddenException


settings = get_settings()


def _now() -> datetime:
    return datetime.utcnow()


def _is_base64_like(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) < 2000:
        return False
    # Heuristic: large base64 strings tend to be high-entropy and long without spaces.
    return " " not in value and "\n" not in value and len(value) > 8000


def _validate_job_input(payload: Dict[str, Any]) -> None:
    # Keep payload small and prevent accidental base64 uploads.
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    max_bytes = int(getattr(settings, "JOBS_MAX_INPUT_BYTES", 20_000))
    if len(raw) > max_bytes:
        raise BadRequestException("Job input too large.")

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and "base64" in k.lower():
                    raise BadRequestException("Job input must not include base64 data.")
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        else:
            if _is_base64_like(obj):
                raise BadRequestException("Job input must not include base64 data.")

    walk(payload)


class JobsService:
    @staticmethod
    def _collection():
        return Database.get_collection("jobs")

    @classmethod
    async def get_job_for_user(cls, job_id: str, user_id: str) -> dict:
        doc = await cls._collection().find_one({"job_id": job_id})
        if not doc:
            raise NotFoundException("Job not found")
        if (doc.get("user_id") or "") != user_id:
            raise ForbiddenException("Job not found")
        doc["id"] = str(doc.pop("_id"))
        return doc

    @classmethod
    async def find_idempotent_job(
        cls, *, user_id: str, job_type: str, idempotency_key: str
    ) -> Optional[dict]:
        window_h = int(getattr(settings, "JOBS_IDEMPOTENCY_WINDOW_HOURS", 6))
        since = _now() - timedelta(hours=window_h)
        cursor = cls._collection().find(
            {
                "user_id": user_id,
                "type": job_type,
                "idempotency_key": idempotency_key,
                "created_at": {"$gte": since},
            }
        ).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        doc = docs[0] if docs else None
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return doc

    @classmethod
    async def create_job(
        cls,
        *,
        user_id: str,
        job_type: str,
        job_input: Dict[str, Any],
        idempotency_key: Optional[str],
    ) -> dict:
        _validate_job_input(job_input or {})
        now = _now()

        oid = ObjectId()
        job_id = str(oid)

        doc = {
            "_id": oid,
            "job_id": job_id,
            "user_id": user_id,
            "type": job_type,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "celery_task_id": None,
            "input": job_input or {},
            "result": None,
            "error": None,
            "attempts": 0,
            "idempotency_key": idempotency_key,
        }

        await cls._collection().insert_one(doc)
        doc["id"] = str(doc.pop("_id"))
        return doc

    @classmethod
    async def attach_task_id(cls, job_id: str, task_id: str) -> None:
        await cls._collection().update_one(
            {"job_id": job_id},
            {"$set": {"celery_task_id": task_id, "updated_at": _now()}},
        )
