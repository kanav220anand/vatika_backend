"""Celery tasks (sync) — INFRA-001 / JOBS-001."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from app.jobs.mongo_clients import get_pymongo_db
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


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


# =============================================================================
# Water Reminder Tasks
# =============================================================================

def _run_async(coro):
    """Run async function in sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.worker.tasks.generate_daily_water_reminders", acks_late=True)
def generate_daily_water_reminders() -> Dict[str, Any]:
    """
    Generate water reminder notifications for all users.
    
    This task is scheduled to run daily at 8 AM IST via Celery Beat.
    It finds all plants needing water and creates batched notifications.
    
    Returns:
        Dict with statistics about generated reminders.
    """
    from app.core.database import Database
    from app.notifications.water_reminder_service import WaterReminderService
    
    logger.info("Starting daily water reminder generation")
    
    try:
        # Initialize database connection for async operations
        _run_async(Database.connect())
        
        # Generate reminders
        stats = _run_async(WaterReminderService.generate_daily_reminders())
        
        logger.info(f"Daily water reminders complete: {stats}")
        return stats
    
    except Exception as e:
        logger.error(f"Failed to generate daily water reminders: {e}")
        raise


@celery_app.task(name="app.worker.tasks.process_snoozed_reminders", acks_late=True)
def process_snoozed_reminders() -> Dict[str, Any]:
    """
    Process snoozed water reminders that are due for re-delivery.
    
    This task runs every 30 minutes to check for snoozed notifications
    that have passed their snooze time and need to be sent again.
    
    Returns:
        Dict with statistics about processed reminders.
    """
    from app.core.database import Database
    from app.notifications.water_reminder_service import WaterReminderService
    
    logger.info("Processing snoozed water reminders")
    
    try:
        # Initialize database connection
        _run_async(Database.connect())
        
        # Process snoozed reminders
        stats = _run_async(WaterReminderService.process_snoozed_reminders())
        
        if stats.get("sent", 0) > 0:
            logger.info(f"Processed snoozed reminders: {stats}")
        
        return stats
    
    except Exception as e:
        logger.error(f"Failed to process snoozed reminders: {e}")
        raise


@celery_app.task(name="app.worker.tasks.generate_user_water_reminder", acks_late=True)
def generate_user_water_reminder(user_id: str) -> Dict[str, Any]:
    """
    Generate water reminder for a specific user on demand.
    
    Can be triggered manually or by other events (e.g., app open).
    
    Args:
        user_id: User's MongoDB ObjectId string.
        
    Returns:
        Dict with notification details if created.
    """
    from app.core.database import Database
    from app.notifications.water_reminder_service import WaterReminderService
    
    logger.info(f"Generating water reminder for user {user_id}")
    
    try:
        _run_async(Database.connect())
        result = _run_async(WaterReminderService.generate_user_water_reminder(user_id))
        
        if result:
            logger.info(f"Generated reminder for user {user_id}: {result}")
        
        return result or {"generated": False}
    
    except Exception as e:
        logger.error(f"Failed to generate reminder for user {user_id}: {e}")
        raise


@celery_app.task(name="app.worker.tasks.send_push_notification", acks_late=True)
def send_push_notification(
    user_id: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Send push notification to a user.
    
    Generic task for sending push notifications.
    
    Args:
        user_id: User's MongoDB ObjectId string.
        title: Notification title.
        body: Notification body.
        data: Optional data payload.
        
    Returns:
        Dict with delivery result.
    """
    from app.core.database import Database
    from app.notifications.push_service import PushNotificationService
    
    logger.info(f"Sending push notification to user {user_id}")
    
    try:
        _run_async(Database.connect())
        result = _run_async(
            PushNotificationService.send_push(
                user_id=user_id,
                title=title,
                body=body,
                data=data
            )
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Failed to send push to user {user_id}: {e}")
        raise

