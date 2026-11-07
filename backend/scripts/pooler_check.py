#!/usr/bin/env python
"""
Pooler check: runs concurrent queries through the async pooled connection.
Verifies prepared statement cache is disabled for PgBouncer compatibility.
Reports any prepared statement errors that would occur with misconfigured asyncpg.
"""
import asyncio
import sys
import logging
import os
from pathlib import Path

# Load .env from parent directory
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def test_pooler_connection(pooled_url: str, num_queries: int = 20):
    """
    Run concurrent queries through the pooled connection to verify no prepared statement caching issues.
    If statement_cache_size=0 is missing, we'll see "prepared statement X not found" errors.
    """
    if not pooled_url:
        logger.error("SUPABASE_POOLED_URL not set")
        sys.exit(1)

    # Convert to asyncpg and add prepared_statement_cache_size=0
    url = pooled_url.replace("postgresql://", "postgresql+asyncpg://")
    if "?" not in url:
        url += "?prepared_statement_cache_size=0"
    else:
        url += "&prepared_statement_cache_size=0"

    engine = create_async_engine(
        url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        connect_args={
            "statement_cache_size": 0,
            "max_cached_statement_lifetime": 0,
            "max_cacheable_statement_size": 0,
        },
    )

    async def run_query(session_id: int):
        """Run a query from a session."""
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                result = await session.execute(text("SELECT :val as value"), {"val": session_id})
                row = result.fetchone()
                return session_id, row[0], None
            except Exception as e:
                return session_id, None, str(e)

    logger.info(f"Running {num_queries} concurrent queries through async pooled connection...")
    tasks = [run_query(i) for i in range(num_queries)]
    results = await asyncio.gather(*tasks)

    errors = [r for r in results if r[2] is not None]
    if errors:
        logger.error("FAILED. Errors detected:")
        for session_id, _, error in errors:
            logger.error(f"   Session {session_id}: {error}")
        await engine.dispose()
        sys.exit(1)
    else:
        logger.info(f"PASSED. All {num_queries} queries succeeded.")
        logger.info("  - prepared_statement_cache_size=0 in URL: ENABLED")
        logger.info("  - statement_cache_size=0 in connect_args: ENABLED")
        logger.info("  - Async engine (API): OK")
        await engine.dispose()
        sys.exit(0)


if __name__ == "__main__":
    pooled_url = os.getenv("SUPABASE_POOLED_URL", "")
    asyncio.run(test_pooler_connection(pooled_url))
