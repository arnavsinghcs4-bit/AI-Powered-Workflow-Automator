"""Celery worker configuration."""

from celery import Celery
from celery.schedules import crontab

from app.config import config

celery_app = Celery(
    "workflow_automator",
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "reset-stale-runs": {
            "task": "scheduler.reset_stale_runs",
            "schedule": 60.0,  # Every 60 seconds
        },
    },
)
