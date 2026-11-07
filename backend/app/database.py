"""Database configuration and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import config

# Pooled engine for API/worker (PgBouncer transaction mode)
# Add prepared_statement_cache_size=0 to URL for asyncpg + PgBouncer compatibility
pooled_url = config.SUPABASE_POOLED_URL.replace(
    "postgresql://", "postgresql+asyncpg://"
)
if "?" not in pooled_url:
    pooled_url += "?prepared_statement_cache_size=0"
else:
    pooled_url += "&prepared_statement_cache_size=0"

pooled_engine = create_async_engine(
    pooled_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    connect_args={
        "statement_cache_size": 0,
        "max_cached_statement_lifetime": 0,
        "max_cacheable_statement_size": 0,
        "command_timeout": 10,
    },
)

# Async session factory
async_session_maker = async_sessionmaker(
    pooled_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """Dependency: return a session for a route."""
    async with async_session_maker() as session:
        yield session
