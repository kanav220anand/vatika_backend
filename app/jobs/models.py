"""Jobs models (JOBS-001)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "succeeded", "failed"]


class JobCreateRequest(BaseModel):
    type: str = Field(..., description="Job type (whitelisted)")
    input: Dict[str, Any] = Field(default_factory=dict, description="Small JSON payload (never base64).")
    idempotency_key: Optional[str] = Field(default=None, max_length=200)


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobResponse(BaseModel):
    job_id: str
    user_id: Optional[str] = None
    type: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    celery_task_id: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts: int = 0
    idempotency_key: Optional[str] = None

