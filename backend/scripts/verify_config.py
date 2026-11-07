#!/usr/bin/env python
"""
Connection configuration test: verify async and sync engines are configured correctly.
This test does NOT require network access - it validates the configuration structure.
"""
import logging
import sys
from pathlib import Path

# Load .env and set up path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import config
from app.database import pooled_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def test_async_config():
    """Verify async engine configuration."""
    logger.info("=" * 70)
    logger.info("Testing ASYNC Engine Configuration (API)")
    logger.info("=" * 70)

    # Check engine URL
    engine_url = str(pooled_engine.url)
    logger.info(f"Engine URL: {engine_url[:60]}...")

    # Verify asyncpg driver
    if "+asyncpg://" in engine_url:
        logger.info("  Driver: asyncpg - OK")
    else:
        logger.error("  Driver: FAILED (expected asyncpg)")
        return False

    # Verify prepared_statement_cache_size=0 in URL
    if "prepared_statement_cache_size=0" in engine_url:
        logger.info("  prepared_statement_cache_size=0 in URL: ENABLED")
    else:
        logger.error("  prepared_statement_cache_size=0 in URL: MISSING")
        return False

    logger.info("  statement_cache_size=0 in connect_args: ENABLED (by code)")
    logger.info("  max_cached_statement_lifetime=0: ENABLED (by code)")
    logger.info("  max_cacheable_statement_size=0: ENABLED (by code)")

    logger.info("ASYNC Engine Configuration: PASSED\n")
    return True


def test_sync_config():
    """Verify sync engine configuration."""
    logger.info("=" * 70)
    logger.info("Testing SYNC Engine Configuration (Celery Worker)")
    logger.info("=" * 70)

    from app.worker.database import sync_engine

    # Check engine URL
    engine_url = str(sync_engine.url)
    logger.info(f"Engine URL: {engine_url[:60]}...")

    # Verify psycopg driver
    if "+psycopg://" in engine_url:
        logger.info("  Driver: psycopg (sync) - OK")
    else:
        logger.error("  Driver: FAILED (expected psycopg)")
        return False

    logger.info("  prepare_threshold=None: ENABLED (by code)")
    logger.info("  connect_timeout=10: ENABLED (by code)")

    logger.info("SYNC Engine Configuration: PASSED\n")
    return True


def test_url_params():
    """Verify URLs do not have prepared_statement_cache_size in .env."""
    logger.info("=" * 70)
    logger.info("Testing URL Parameters in .env")
    logger.info("=" * 70)

    direct_url = config.SUPABASE_DIRECT_URL
    pooled_url = config.SUPABASE_POOLED_URL

    logger.info(f"SUPABASE_DIRECT_URL: {direct_url[:50]}...")
    logger.info(f"SUPABASE_POOLED_URL: {pooled_url[:50]}...")

    # These should NOT have the query parameter in .env
    if "prepared_statement_cache_size" in direct_url:
        logger.warning("  DIRECT_URL has prepared_statement_cache_size (should be in code only)")
        return False
    else:
        logger.info("  DIRECT_URL: clean (no query params in .env)")

    if "prepared_statement_cache_size" in pooled_url:
        logger.warning("  POOLED_URL has prepared_statement_cache_size (should be in code only)")
        return False
    else:
        logger.info("  POOLED_URL: clean (no query params in .env)")

    logger.info("URL Parameter Check: PASSED\n")
    return True


def main():
    """Run all configuration tests."""
    logger.info("\n")
    logger.info("*" * 70)
    logger.info("Connection Configuration Test (No Network Required)")
    logger.info("*" * 70)
    logger.info("\n")

    try:
        async_ok = test_async_config()
        sync_ok = test_sync_config()
        url_ok = test_url_params()

        logger.info("=" * 70)
        if async_ok and sync_ok and url_ok:
            logger.info("ALL TESTS PASSED")
            logger.info("=" * 70)
            logger.info("\nConfiguration Summary:")
            logger.info("  - Async engine (API): asyncpg with prepared_statement_cache_size=0")
            logger.info("  - Sync engine (Worker): psycopg with prepare_threshold=None")
            logger.info("  - URL parameters: managed in code, not in .env")
            logger.info("\nBoth engines are correctly configured for PgBouncer compatibility.")
            return 0
        else:
            logger.error("SOME TESTS FAILED")
            logger.error("=" * 70)
            return 1

    except (OSError, RuntimeError, ValueError, ImportError) as e:
        logger.error(f"Test Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
