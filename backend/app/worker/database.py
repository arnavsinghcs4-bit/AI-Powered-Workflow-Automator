"""Sync database configuration for Celery worker."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import QueuePool

from app.config import config


def get_sync_engine() -> Engine:
    """
    Create a sync engine for Celery worker with psycopg3.
    Uses prepare_threshold=None to disable prepared statements for PgBouncer compatibility.
    """
    # Convert to psycopg driver (sync)
    sync_url = config.SUPABASE_POOLED_URL.replace(
        "postgresql://", "postgresql+psycopg://"
    )

    engine = create_engine(
        sync_url,
        echo=False,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={
            "prepare_threshold": None,  # Disable prepared statements for PgBouncer
            "connect_timeout": 10,
        },
    )

    return engine


# Singleton instance for use in Celery tasks
sync_engine = get_sync_engine()
