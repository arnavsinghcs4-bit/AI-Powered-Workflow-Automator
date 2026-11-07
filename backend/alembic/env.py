"""
Alembic configuration for database migrations.
"""

import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Get database URL: prefer ALEMBIC_DATABASE_URL for testing, fall back to SUPABASE_DIRECT_URL
database_url = os.getenv("ALEMBIC_DATABASE_URL", os.getenv("SUPABASE_DIRECT_URL", ""))

if not database_url:
    raise ValueError("ALEMBIC_DATABASE_URL or SUPABASE_DIRECT_URL must be set.")

# Convert to asyncpg driver
database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

config = context.config
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = create_async_engine(
        database_url,
        echo=False,
        poolclass=None,  # No connection pooling for migrations
    )

    async with connectable.begin() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
