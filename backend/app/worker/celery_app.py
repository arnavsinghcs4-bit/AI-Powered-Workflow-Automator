"""Celery worker configuration."""

from celery import Celery

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
)
