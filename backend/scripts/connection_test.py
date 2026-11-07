#!/usr/bin/env python
"""
Connection test: verify both async (API) and sync (worker) engines connect.
Tests:
1. Async engine with prepared_statement_cache_size=0 (asyncpg + PgBouncer)
2. Sync engine with prepare_threshold=None (psycopg3 + PgBouncer)
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def test_async_connection(pooled_url: str):
    """Test async engine (for API)."""
    logger.info("Testing ASYNC connection (asyncpg + PgBouncer)...")

    if not pooled_url:
        logger.error("SUPABASE_POOLED_URL not set")
        return False

    # Convert to asyncpg and add prepared_statement_cache_size=0
    async_url = pooled_url.replace("postgresql://", "postgresql+asyncpg://")
    if "?" not in async_url:
        async_url += "?prepared_statement_cache_size=0"
    else:
        async_url += "&prepared_statement_cache_size=0"

    try:
        engine = create_async_engine(
            async_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            connect_args={
                "statement_cache_size": 0,
                "max_cached_statement_lifetime": 0,
                "max_cacheable_statement_size": 0,
                "command_timeout": 10,
            },
        )

        async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Test query
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()
            logger.info(f"  Connected to: {version[:60]}...")
            logger.info("  prepared_statement_cache_size=0: ENABLED")
            logger.info("  statement_cache_size=0 in connect_args: ENABLED")

        await engine.dispose()
        logger.info("ASYNC connection: PASSED\n")
        return True

    except (OSError, RuntimeError, ValueError) as e:
        logger.error(f"ASYNC connection: FAILED - {e}\n")
        return False


def test_sync_connection(pooled_url: str):
    """Test sync engine (for Celery worker)."""
    logger.info("Testing SYNC connection (psycopg3 + PgBouncer)...")

    if not pooled_url:
        logger.error("SUPABASE_POOLED_URL not set")
        return False

    # Convert to psycopg (sync)
    sync_url = pooled_url.replace("postgresql://", "postgresql+psycopg://")

    try:
        engine = create_engine(
            sync_url,
            echo=False,
            pool_pre_ping=True,
            connect_args={
                "prepare_threshold": None,  # Disable prepared statements
                "connect_timeout": 10,
            },
        )

        # Test query
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            logger.info(f"  Connected to: {version[:60]}...")
            logger.info("  prepare_threshold=None: ENABLED")

        engine.dispose()
        logger.info("SYNC connection: PASSED\n")
        return True

    except (OSError, RuntimeError, ValueError) as e:
        logger.error(f"SYNC connection: FAILED - {e}\n")
        return False


async def main():
    """Run both connection tests."""
    pooled_url = os.getenv("SUPABASE_POOLED_URL", "")

    if not pooled_url:
        logger.error("SUPABASE_POOLED_URL environment variable not set")
        sys.exit(1)

    logger.info("=" * 70)
    logger.info("Connection Test: Async (API) + Sync (Worker)")
    logger.info("=" * 70 + "\n")

    # Test async
    async_ok = await test_async_connection(pooled_url)

    # Test sync
    sync_ok = test_sync_connection(pooled_url)

    logger.info("=" * 70)
    if async_ok and sync_ok:
        logger.info("BOTH connections PASSED")
        logger.info("=" * 70)
        sys.exit(0)
    else:
        logger.info("Some connections FAILED")
        logger.info("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
