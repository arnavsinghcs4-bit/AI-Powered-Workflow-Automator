"""Testing configuration and fixtures."""
import os
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Safety guard: DATABASE_TEST_URL must be set and not point to Supabase
test_url = os.getenv("DATABASE_TEST_URL", "").strip()

if not test_url:
    raise ValueError(
        "DATABASE_TEST_URL environment variable must be set. "
        "Use localhost, 127.0.0.1, or a CI service hostname (e.g., postgres:5432)."
    )

# Allowlist of safe test database hosts
allowed_hosts = ("localhost", "127.0.0.1", "postgres", "postgres:5432")
is_safe = any(host in test_url for host in allowed_hosts)

if not is_safe or "supabase.co" in test_url:
    raise ValueError(
        f"DATABASE_TEST_URL points to an unsafe host: {test_url}. "
        f"Must be one of: {', '.join(allowed_hosts)}. "
        f"Never point to a Supabase project."
    )

# Create test engine
test_engine = create_async_engine(
    test_url.replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,
)

TestAsyncSessionMaker = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture
async def db_session():
    """Provide a test database session."""
    async with TestAsyncSessionMaker() as session:
        yield session


@pytest.fixture
def mock_redis():
    """Mock Redis for testing."""
    # Placeholder; will use fakeredis or responses library
    pass
