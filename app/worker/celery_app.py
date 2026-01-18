"""Celery app bootstrap (AWS SQS broker) — INFRA-001."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings


settings = get_settings()

QUEUE_PREFIX = (settings.CELERY_QUEUE_PREFIX or "vatika-").strip()
# Celery SQS transport applies `queue_name_prefix` to queue names.
# Use the logical queue name "default" so the actual SQS queue becomes "<prefix>default".
DEFAULT_QUEUE = "default"
ACTUAL_DEFAULT_QUEUE_NAME = f"{QUEUE_PREFIX}{DEFAULT_QUEUE}"

celery_app = Celery(
    "vatisha",
    broker=(settings.CELERY_BROKER_URL or "sqs://").strip(),
    include=["app.worker.tasks"],
)

transport_options: dict = {
    "region": (settings.AWS_REGION or "").strip(),
    "queue_name_prefix": QUEUE_PREFIX,
    "visibility_timeout": int(settings.CELERY_VISIBILITY_TIMEOUT),
    "polling_interval": float(settings.CELERY_POLLING_INTERVAL),
    "wait_time_seconds": int(settings.CELERY_WAIT_TIME_SECONDS),
}

default_queue_url = (settings.SQS_DEFAULT_QUEUE_URL or "").strip()
if default_queue_url:
    # Use predefined queue URLs so Celery uses exactly the queue URL provided.
    transport_options["predefined_queues"] = {
        DEFAULT_QUEUE: {"url": default_queue_url},
    }

celery_app.conf.update(
    broker_transport_options=transport_options,
    task_default_queue=DEFAULT_QUEUE,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
)

if settings.CELERY_TASK_TIME_LIMIT:
    celery_app.conf.task_time_limit = int(settings.CELERY_TASK_TIME_LIMIT)
if settings.CELERY_TASK_SOFT_TIME_LIMIT:
    celery_app.conf.task_soft_time_limit = int(settings.CELERY_TASK_SOFT_TIME_LIMIT)
