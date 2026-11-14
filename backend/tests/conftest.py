"""Testing configuration and fixtures."""

import os
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
import sqlalchemy.exc
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Force-set test environment BEFORE any app imports (setdefault would lose to CI)
os.environ["ENABLE_RATE_LIMITING"] = "false"
os.environ["JWT_SECRET"] = "test-secret-key-at-least-32-characters-long-12345"
os.environ["ENV"] = "test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"  # Test Redis URL

# Safety guard: DATABASE_TEST_URL must be set and not point to Supabase
test_url = os.getenv("DATABASE_TEST_URL", "").strip()

if not test_url:
    raise ValueError(
        "DATABASE_TEST_URL environment variable must be set. "
        "Use localhost, 127.0.0.1, or a CI service hostname (e.g., postgres:5432)."
    )

# Validate safe test database hosts using urlparse
parsed = urlparse(
    test_url if test_url.startswith("postgresql://") else f"postgresql://{test_url}"
)
allowed_hosts = ("localhost", "127.0.0.1", "postgres")
hostname = parsed.hostname or ""

is_safe = (
    any(hostname.startswith(host) for host in allowed_hosts)
    and "supabase.co" not in test_url
)

if not is_safe:
    raise ValueError(
        f"DATABASE_TEST_URL points to an unsafe host: {hostname}. "
        f"Must be one of: {', '.join(allowed_hosts)}. "
        f"Never point to a Supabase project."
    )

# Sync URL for worker tests (psycopg driver)
test_sync_url = test_url.replace("postgresql://", "postgresql+psycopg://")


async def _truncate_test_db(engine):
    """Clean test database using autocommit to ensure committed truncate."""
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE users, refresh_tokens RESTART IDENTITY CASCADE")
        )


@pytest.fixture(autouse=True)
def _patch_worker_db():
    """Patch worker's sync_engine to use test database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import QueuePool

    test_engine = create_engine(
        test_sync_url,
        echo=False,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={
            "prepare_threshold": None,
            "connect_timeout": 10,
        },
    )

    # Patch the engine and recreate the session maker
    test_session_maker = sessionmaker(bind=test_engine, expire_on_commit=False)

    with patch("app.worker.tasks.sync_engine", test_engine):
        with patch("app.worker.database.sync_engine", test_engine):
            with patch("app.worker.tasks._sync_session_maker", test_session_maker):
                yield

    test_engine.dispose()


@pytest.fixture(autouse=True)
def _patch_celery():
    """Patch Celery app to avoid connecting to Redis in tests."""
    mock_celery = MagicMock()
    mock_celery.send_task = MagicMock()
    with patch("app.worker.celery_app.celery_app", mock_celery):
        yield


@pytest.fixture
async def db_session():
    """Provide a test database session with fresh engine and no pooling.

    Creates a new engine per test to avoid event loop conflicts.
    Uses NullPool to prevent connection reuse across tests.
    Cleans tables before and after each test to prevent data leakage.
    """
    # Create fresh engine inside fixture to avoid event loop issues
    engine = create_async_engine(
        test_url.replace("postgresql://", "postgresql+asyncpg://"),
        echo=False,
        poolclass=NullPool,  # No connection pooling in tests
    )

    try:
        # Clean before test (in case prior test crashed)
        await _truncate_test_db(engine)

        async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with async_session_maker() as session:
            yield session
    finally:
        # Clean after test and dispose connections
        try:
            await _truncate_test_db(engine)
        except sqlalchemy.exc.SQLAlchemyError:
            pass  # Ignore cleanup errors if DB already cleaned, dispose anyway
        finally:
            await engine.dispose()


@pytest.fixture
async def client(db_session):
    """Create test client with dependency overrides for db_session."""
    from app.database import get_session

    async def override_get_session():
        return db_session

    from app.main import app

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(client):
    """Create a test user via /auth/register and return dict with email/password."""
    email = "testuser@example.com"
    password = "SecurePassword123"
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    return {"email": email, "password": password}


@pytest.fixture
def mock_redis():
    """Mock Redis for testing without needing a Redis daemon."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=True)
    mock.close = AsyncMock(return_value=None)
    return mock
