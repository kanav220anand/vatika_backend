"""Jobs API endpoints — JOBS-001."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Path, Header

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.exceptions import BadRequestException, ForbiddenException
from app.admin.dependencies import require_admin_api_key
from app.jobs.models import JobCreateRequest, JobCreateResponse, JobResponse
from app.jobs.service import JobsService


router = APIRouter(prefix="/jobs", tags=["Jobs"])
settings = get_settings()


ALLOWED_JOB_TYPES = {
    "ping": "app.worker.tasks.ping",
}


def _get_celery():
    try:
        from app.worker.celery_app import celery_app, DEFAULT_QUEUE

        return celery_app, DEFAULT_QUEUE
    except Exception as e:
        raise BadRequestException("Jobs are not available (Celery not configured).") from e


def _can_debug_jobs(debug_jobs_endpoints: bool, x_admin_api_key: str) -> bool:
    if debug_jobs_endpoints:
        return True
    try:
        require_admin_api_key(x_admin_api_key=x_admin_api_key)
        return True
    except Exception:
        return False


@router.post("", response_model=JobCreateResponse)
async def create_job(
    body: JobCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    job_type = (body.type or "").strip()
    if job_type not in ALLOWED_JOB_TYPES:
        raise BadRequestException("Unsupported job type.")

    if body.idempotency_key:
        existing = await JobsService.find_idempotent_job(
            user_id=current_user["id"],
            job_type=job_type,
            idempotency_key=body.idempotency_key,
        )
        if existing:
            return JobCreateResponse(job_id=existing["job_id"], status=existing.get("status", "queued"))

    job = await JobsService.create_job(
        user_id=current_user["id"],
        job_type=job_type,
        job_input=body.input or {},
        idempotency_key=body.idempotency_key,
    )

    task_name = ALLOWED_JOB_TYPES[job_type]
    try:
        celery_app, default_queue = _get_celery()
        async_result = celery_app.send_task(task_name, args=[job["job_id"]], queue=default_queue)
        await JobsService.attach_task_id(job["job_id"], async_result.id)
    except Exception as e:
        now = datetime.utcnow()
        await JobsService._collection().update_one(
            {"job_id": job["job_id"]},
            {
                "$set": {
                    "status": "failed",
                    "error": f"Failed to enqueue job: {type(e).__name__}",
                    "updated_at": now,
                    "finished_at": now,
                }
            },
        )
        raise BadRequestException("Failed to enqueue job. Check worker/broker configuration.")

    return JobCreateResponse(job_id=job["job_id"], status="queued")


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str = Path(..., description="Job ID"),
    current_user: dict = Depends(get_current_user),
):
    doc = await JobsService.get_job_for_user(job_id, current_user["id"])
    return JobResponse(
        job_id=doc["job_id"],
        user_id=doc.get("user_id"),
        type=doc["type"],
        status=doc["status"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        started_at=doc.get("started_at"),
        finished_at=doc.get("finished_at"),
        celery_task_id=doc.get("celery_task_id"),
        input=doc.get("input") or {},
        result=doc.get("result"),
        error=doc.get("error"),
        attempts=int(doc.get("attempts") or 0),
        idempotency_key=doc.get("idempotency_key"),
    )


@router.post("/{job_id}/retry", response_model=JobCreateResponse)
async def retry_job(
    job_id: str = Path(..., description="Job ID"),
    x_admin_api_key: str = Header(default="", alias="X-ADMIN-API-KEY"),
):
    if not _can_debug_jobs(bool(getattr(settings, "DEBUG_JOBS_ENDPOINTS", False)), x_admin_api_key):
        raise ForbiddenException("Admin access denied")

    doc = await JobsService._collection().find_one({"job_id": job_id})
    if not doc:
        raise BadRequestException("Job not found")
    if doc.get("status") not in {"failed"}:
        raise BadRequestException("Only failed jobs can be retried.")

    task_name = ALLOWED_JOB_TYPES.get(doc.get("type") or "")
    if not task_name:
        raise BadRequestException("Unsupported job type.")

    now = datetime.utcnow()
    await JobsService._collection().update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": "queued",
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
                "error": None,
                "result": None,
            }
        },
    )

    try:
        celery_app, default_queue = _get_celery()
        async_result = celery_app.send_task(task_name, args=[job_id], queue=default_queue)
        await JobsService.attach_task_id(job_id, async_result.id)
    except Exception:
        raise BadRequestException("Failed to enqueue job. Check worker/broker configuration.")

    return JobCreateResponse(job_id=job_id, status="queued")
