"""Health check endpoint."""
import logging
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as redis

from app.database import async_session_maker
from app.config import config

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health():
    """Health check endpoint. Verifies DB and Redis connectivity."""
    db_status = "failed"
    redis_status = "failed"

    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Health check DB failed: {e}")

    try:
        redis_client = redis.from_url(config.REDIS_URL)
        await redis_client.ping()
        redis_status = "connected"
        await redis_client.close()
    except Exception as e:
        logger.error(f"Health check Redis failed: {e}")

    if db_status == "connected" and redis_status == "connected":
        return {"status": "ok", "db": "connected", "redis": "connected"}
    else:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "degraded",
                "db": db_status,
                "redis": redis_status,
            },
        )
