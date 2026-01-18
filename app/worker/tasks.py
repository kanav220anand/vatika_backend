"""Celery tasks (sync) — INFRA-001 / JOBS-001."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from app.jobs.mongo_clients import get_pymongo_db
from app.worker.celery_app import celery_app


def _now() -> datetime:
    return datetime.utcnow()


def _jobs_collection():
    return get_pymongo_db()["jobs"]


def _mark_running(job_id: str) -> Optional[dict]:
    now = _now()
    return _jobs_collection().find_one_and_update(
        {"job_id": job_id, "status": "queued"},
        {
            "$set": {"status": "running", "started_at": now, "updated_at": now},
            "$inc": {"attempts": 1},
        },
        return_document=ReturnDocument.AFTER,
    )


def _finish_once(job_id: str, update: Dict[str, Any]) -> None:
    """
    Update a job as finished only once (idempotent under SQS redelivery).
    """
    _jobs_collection().update_one(
        {"job_id": job_id, "finished_at": {"$exists": False}},
        update,
    )


@celery_app.task(name="app.worker.tasks.ping", acks_late=True)
def ping(job_id: str) -> Dict[str, Any]:
    """
    Example task proving the pipeline works.

    Always pass only job_id via SQS; fetch inputs from Mongo if needed.
    """
    job = _jobs_collection().find_one({"job_id": job_id})
    if not job:
        return {"ok": False, "error": "job_not_found"}

    if job.get("status") == "succeeded":
        return job.get("result") or {"message": "pong"}

    running = _mark_running(job_id)
    if running is None:
        # Might be redelivered or already running/failed; avoid double-running if finished.
        job = _jobs_collection().find_one({"job_id": job_id}) or {}
        if job.get("status") != "running":
            return job.get("result") or {"ok": False, "status": job.get("status")}

    try:
        time.sleep(0.2)
        result = {"message": "pong", "ts": _now().isoformat() + "Z"}
        finished_at = _now()
        _finish_once(
            job_id,
            {
                "$set": {
                    "status": "succeeded",
                    "result": result,
                    "error": None,
                    "updated_at": finished_at,
                    "finished_at": finished_at,
                }
            },
        )
        return result
    except Exception as e:
        finished_at = _now()
        err = str(e)
        if len(err) > 1200:
            err = err[:1200] + "…"
        _finish_once(
            job_id,
            {
                "$set": {
                    "status": "failed",
                    "error": err,
                    "updated_at": finished_at,
                    "finished_at": finished_at,
                }
            },
        )
        raise

