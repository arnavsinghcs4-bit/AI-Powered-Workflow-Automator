# Phase 1 Design: Project Scaffold, Docker Compose, Supabase Connection, Alembic Migrations

**Date:** 2026-11-07  
**Phase:** 1 of 9  
**Scope:** Foundation layer — infrastructure, schema, health check, CI pipeline.

---

## Overview

Phase 1 establishes a production-ready local development environment and remote database connection. By the end of this phase:

- `docker-compose up` starts all services (API, worker, Redis, frontend placeholder)
- `make migrate` applies all 7-table schema to Supabase via Alembic
- `GET /health` confirms DB and Redis connectivity
- CI runs lint (ruff) and tests against an isolated test database
- `.env.example` documents all configuration; real secrets stay in `.env` (not committed)

### Tech Choices

- **Database:** Supabase (remote Postgres). Two connections:
  - **Direct:** For Alembic migrations (session-pooler URL if direct connections fail)
  - **Pooled:** For API and worker (PgBouncer transaction pooler, asyncpg with `statement_cache_size=0`)
- **Testing:** Throwaway Postgres container in CI, isolated local test DB for development
- **Migrations:** Alembic only; no schema changes via Supabase dashboard
- **Tooling:** Makefile, pre-commit with ruff, docker-compose, GitHub Actions

---

## Folder Structure

```
AI-Powered-Workflow-Automator/
├── .github/
│   └── workflows/
│       └── ci.yml                    # ruff lint + format check + pytest (with throwaway Postgres + Redis)
├── .gitignore
├── .pre-commit-config.yaml
├── .env.example                      # root level, single shared .env
├── Makefile
├── docker-compose.yml
├── README.md
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI app, routes, startup/shutdown (async only)
│   │   ├── config.py                 # environment config, database URLs
│   │   ├── database.py               # SQLAlchemy async sessionmaker, pooled connection only
│   │   ├── health.py                 # GET /health endpoint
│   │   ├── schemas.py                # Pydantic models (shared DTO layer)
│   │   │
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── models.py             # User SQLAlchemy model
│   │   │   └── routes.py             # placeholder (Phase 2: register, login, refresh)
│   │   │
│   │   ├── pipelines/
│   │   │   ├── __init__.py
│   │   │   ├── models.py             # Pipeline, PipelineStep models
│   │   │   └── routes.py             # placeholder (Phase 3: CRUD)
│   │   │
│   │   ├── files/
│   │   │   ├── __init__.py
│   │   │   └── routes.py             # placeholder (Phase 3: upload to Supabase Storage)
│   │   │
│   │   ├── jobs/
│   │   │   ├── __init__.py
│   │   │   ├── models.py             # Job, StepRun, LLMCall models
│   │   │   └── routes.py             # placeholder (Phase 4+: job status, results)
│   │   │
│   │   └── worker/
│   │       ├── __init__.py
│   │       ├── celery_app.py         # Celery config, broker/backend URLs
│   │       └── tasks.py              # placeholder (Phase 4: job execution)
│   │
│   ├── alembic/
│   │   ├── versions/
│   │   │   └── 001_init_schema.py    # initial 7-table migration with RLS
│   │   ├── env.py                    # Alembic config, accepts ALEMBIC_DATABASE_URL override
│   │   ├── script.py.mako
│   │   └── alembic.ini               # moved to backend/
│   │
│   ├── scripts/
│   │   └── wait-for-db.sh            # health checks for DB and Redis (mounted in container)
│   │
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py               # pytest fixtures, allowlist guard for test DB
│   │   ├── test_health.py            # health endpoint, DB/Redis connectivity
│   │   ├── test_auth.py              # (Phase 2)
│   │   ├── test_pipelines.py         # (Phase 3)
│   │   └── test_jobs.py              # (Phase 4+)
│   │
│   ├── requirements.txt              # FastAPI, SQLAlchemy, asyncpg, Alembic, Celery, etc.
│   ├── requirements-dev.txt          # pytest, pytest-asyncio, ruff, etc.
│   ├── Dockerfile                    # includes netcat for wait-for-db.sh
│   └── .dockerignore
│
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   └── page.tsx                  # placeholder
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── Dockerfile
│   └── next.config.ts
│
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-11-07-phase1-design.md  # this file
```

---

## Configuration & Secrets

### `.env.example`

```bash
# === SUPABASE POSTGRES ===
# Copy both URLs from Supabase's "Connect" panel → "Connection string" → "URI".
# - SUPABASE_DIRECT_URL: session pooler (port 5432, use for one-off connections, schema migrations)
# - SUPABASE_POOLED_URL: transaction pooler (port 6543, use for API/worker with pooling)
# Both should have ?prepared_statement_cache_size=0 in the query string.

SUPABASE_DIRECT_URL=postgresql://postgres.xxxxxx:[password]@aws-0-us-east-1.pooler.supabase.com:5432/postgres?prepared_statement_cache_size=0
SUPABASE_POOLED_URL=postgresql://postgres.xxxxxx:[password]@aws-0-us-east-1.pooler.supabase.com:6543/postgres?prepared_statement_cache_size=0

# === REDIS ===
REDIS_URL=redis://redis:6379

# === JWT ===
JWT_SECRET=your-secret-key-change-me

# === TESTING (isolated from Supabase project) ===
# Use localhost, 127.0.0.1, or the CI service host (e.g., postgres:5432 in GitHub Actions).
# conftest.py aborts pytest if this is empty or points to a supabase.co host.
DATABASE_TEST_URL=postgresql://postgres:postgres@localhost:5432/workflow_automator_test

# === ALEMBIC (optional override for migrations) ===
# If not set, defaults to SUPABASE_DIRECT_URL.
# In CI, set this to DATABASE_TEST_URL to run migrations on the test database.
# ALEMBIC_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/workflow_automator_test
```

### Key Points

- **Never commit `.env`** — git ignores it. Real secrets go in `.env`, placeholders in `.env.example`.
- **SUPABASE_DIRECT_URL:** Session pooler (5432). Used by Alembic for migrations. `prepared_statement_cache_size=0` required.
- **SUPABASE_POOLED_URL:** Transaction pooler (6543). Used by API and worker. `prepared_statement_cache_size=0` required. SQLAlchemy passes `statement_cache_size=0` and unique prepared statement names via connect_args (PgBouncer compatibility).
- **DATABASE_TEST_URL:** Points to localhost or CI test database. Conftest.py enforces an allowlist (localhost, 127.0.0.1, service hostname) and aborts pytest if empty or contains `supabase.co`.
- **ALEMBIC_DATABASE_URL:** Optional. If set, overrides SUPABASE_DIRECT_URL for migrations. Useful in CI to run migrations on the test database instead of production.

---

## Database Schema

### 7 Tables with Row Level Security

All tables have RLS enabled (no policies yet — backend uses the `owner` role). Foreign keys cascade on delete/update for referential integrity.

#### 1. `users`

```sql
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON users FROM anon, authenticated;
```

#### 2. `pipelines`

```sql
CREATE TABLE pipelines (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pipelines_user_id ON pipelines(user_id);
ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pipelines FROM anon, authenticated;
```

#### 3. `pipeline_steps`

```sql
CREATE TABLE pipeline_steps (
  id SERIAL PRIMARY KEY,
  pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  type VARCHAR(50) NOT NULL,
  CHECK (type IN ('extract_text', 'llm_extract', 'validate', 'send_email', 'webhook')),
  config JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(pipeline_id, position)
);

CREATE INDEX idx_pipeline_steps_pipeline_id ON pipeline_steps(pipeline_id);
ALTER TABLE pipeline_steps ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pipeline_steps FROM anon, authenticated;
```

#### 4. `files`

```sql
CREATE TABLE files (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename VARCHAR(255) NOT NULL,
  storage_path VARCHAR(255) NOT NULL,
  mime_type VARCHAR(100),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_files_user_id ON files(user_id);
ALTER TABLE files ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON files FROM anon, authenticated;
```

#### 5. `jobs`

```sql
CREATE TABLE jobs (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  status VARCHAR(50) NOT NULL DEFAULT 'queued',
  CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'needs_review')),
  error TEXT,
  idempotency_key VARCHAR(255) UNIQUE,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_jobs_user_id ON jobs(user_id);
CREATE INDEX idx_jobs_pipeline_id ON jobs(pipeline_id);
CREATE INDEX idx_jobs_file_id ON jobs(file_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_idempotency_key ON jobs(idempotency_key);
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON jobs FROM anon, authenticated;
```

#### 6. `step_runs`

```sql
CREATE TABLE step_runs (
  id SERIAL PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  step_id INTEGER REFERENCES pipeline_steps(id) ON DELETE SET NULL,
  status VARCHAR(50) NOT NULL,
  CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  input JSONB,
  output JSONB,
  error TEXT,
  attempt INTEGER DEFAULT 1,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_step_runs_job_id ON step_runs(job_id);
CREATE INDEX idx_step_runs_step_id ON step_runs(step_id);
ALTER TABLE step_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON step_runs FROM anon, authenticated;
```

#### 7. `llm_calls`

```sql
CREATE TABLE llm_calls (
  id SERIAL PRIMARY KEY,
  step_run_id INTEGER NOT NULL REFERENCES step_runs(id) ON DELETE CASCADE,
  model VARCHAR(100) NOT NULL,
  prompt TEXT NOT NULL,
  response TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd NUMERIC(10, 6),
  latency_ms INTEGER,
  valid_json BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_llm_calls_step_run_id ON llm_calls(step_run_id);
ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON llm_calls FROM anon, authenticated;
```

### Design Rationale

- **RLS enabled + REVOKE:** RLS blocks the Supabase REST API roles (`anon`, `authenticated`) at the database layer. The backend connects as the `owner` role (credentials in connection string) and bypasses RLS. This prevents accidental data leaks through the REST API, even if the backend is compromised.
- **TIMESTAMPTZ:** All timestamps in UTC. Prevents timezone confusion in logs and auditing.
- **CHECK constraints on status:** Database-level validation prevents invalid state transitions from bugs.
- **UNIQUE(pipeline_id, position):** Ensures step positions are sequential per pipeline.
- **step_runs.step_id ON DELETE SET NULL:** When a step is deleted, keep its run history (immutable audit trail). The step definition goes away, but the run record stays.
- **jobs.idempotency_key:** Prevents duplicate job submissions in Phase 6 (rate limiting / daily limits).
- **Cascade delete (user → pipelines → jobs → step_runs → llm_calls):** Deleting a user cleans up all related data atomically. But `step_runs.step_id` is SET NULL to preserve run history even if the step is deleted.
- **JSONB columns:** `pipeline_steps.config`, `step_runs.input/output` store flexible nested data without schema migrations.

---

## SQLAlchemy & Asyncpg Configuration

### Database Connections

**Direct Connection (Alembic migrations only):**
- URL: `SUPABASE_DIRECT_URL` (session pooler, 5432)
- No connection pooling (Alembic uses NullPool)
- Used by: `alembic upgrade head`, `alembic downgrade -1`
- Not used by API or worker

**Pooled Connection (API & Worker only):**
- URL: `SUPABASE_POOLED_URL` (transaction pooler, 6543)
- Prepared statement cache disabled via `prepared_statement_cache_size=0` in query string
- SQLAlchemy also sets `statement_cache_size=0` in connect_args plus unique prepared statement names
- Used by: API routes, Celery worker tasks
- **Why:** PgBouncer transaction mode reuses connections between queries. Prepared statements are server-side, tied to a connection. If a statement is cached on connection A and then reused on connection B (via PgBouncer), you get "prepared statement X not found". Solution: disable caching entirely and let SQLAlchemy generate unique names per statement.

### Code Structure (database.py — API/Worker only)

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import async_sessionmaker
import uuid

# Pooled engine for API/worker
# PgBouncer transaction mode config per SQLAlchemy docs:
# - prepared_statement_cache_size=0 in connection string
# - statement_cache_size=0 in connect_args
# - unique prepared statement names via connection initializer
pooled_engine = create_async_engine(
    config.SUPABASE_POOLED_URL.replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # test connection before use
    connect_args={
        "statement_cache_size": 0,
        "max_cached_statement_lifetime": 0,
        "max_cacheable_statement_size": 0,
        "command_timeout": 10,
    },
)

# Async session factory (not sessionmaker — use async_sessionmaker)
async_session_maker = async_sessionmaker(
    pooled_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_session():
    """Dependency: return a session for a route."""
    async with async_session_maker() as session:
        yield session
```

### Test in Health Check

The health check endpoint includes a database query that catches misconfigured connections:

```python
import redis.asyncio as redis

@app.get("/health")
async def health():
    db_status = "failed"
    redis_status = "failed"
    
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        # Log the detail, but return generic message to client
        app.logger.error(f"Health check DB failed: {e}")
    
    try:
        # Use redis.asyncio for async Redis client
        redis_client = redis.from_url(config.REDIS_URL)
        await redis_client.ping()
        redis_status = "connected"
        await redis_client.close()
    except Exception as e:
        app.logger.error(f"Health check Redis failed: {e}")
    
    if db_status == "connected" and redis_status == "connected":
        return {"status": "ok", "db": "connected", "redis": "connected"}
    else:
        return {
            "status": "degraded",
            "db": db_status,
            "redis": redis_status,
        }, 503  # HTTP 503 Service Unavailable
```

**What's tested:** If `prepared_statement_cache_size=0` or `statement_cache_size=0` is missing, the pooled connection will eventually fail with "prepared statement" errors when running multiple queries. The health check catches this early.

---

## Docker Compose

### `docker-compose.yml`

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - SUPABASE_POOLED_URL=${SUPABASE_POOLED_URL}
      - REDIS_URL=redis://redis:6379
      - JWT_SECRET=${JWT_SECRET}
    depends_on:
      redis:
        condition: service_healthy
    volumes:
      - ./backend:/app
    command: >
      sh -c "
      backend/scripts/wait-for-db.sh &&
      uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
      "

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    environment:
      - SUPABASE_POOLED_URL=${SUPABASE_POOLED_URL}
      - REDIS_URL=redis://redis:6379
      - JWT_SECRET=${JWT_SECRET}
    depends_on:
      redis:
        condition: service_healthy
    volumes:
      - ./backend:/app
    command: >
      sh -c "
      backend/scripts/wait-for-db.sh &&
      celery -A app.worker.celery_app worker --loglevel=info
      "

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    command: npm run dev
```

### Key Points

- **No Postgres container** — all services connect to remote Supabase.
- **API/worker get SUPABASE_POOLED_URL only** — no direct connection needed in containers.
- **`wait-for-db.sh` mounted from backend/scripts** — path is `backend/scripts/wait-for-db.sh` relative to repo root.
- **`depends_on` with healthcheck** — Redis starts and passes health before API/worker attempt connection.
- **Hot reload** — volumes mount code for development; changes restart services.
- **Anonymous node_modules volume** — prevents npm packages from being shadowed by host mount.
- **Migrations manual** — run `make migrate` in a shell, not automatically.
- **No `version:` field** — omitted per specification.

---

## `backend/scripts/wait-for-db.sh`

Located in `backend/scripts/` so it's inside the container mount. Install `netcat` in the Dockerfile.

```bash
#!/bin/bash
# Wait for Supabase and Redis to be reachable before starting services.
# Do NOT run migrations automatically.

DB_URL="${SUPABASE_POOLED_URL}"
REDIS_URL="${REDIS_URL}"

# Extract host and port from SUPABASE_POOLED_URL (assumes postgresql://user:pass@host:port/db)
DB_HOST=$(echo "$DB_URL" | sed -n 's/.*@\([^:]*\).*/\1/p')
DB_PORT=$(echo "$DB_URL" | sed -n 's/.*:\([0-9]*\)\/.*$/\1/p')
if [ -z "$DB_PORT" ]; then DB_PORT=6543; fi

REDIS_HOST=$(echo "$REDIS_URL" | sed -n 's/.*:\/\/\([^:]*\).*/\1/p')
REDIS_PORT=$(echo "$REDIS_URL" | sed -n 's/.*:\([0-9]*\)$/\1/p')
if [ -z "$REDIS_PORT" ]; then REDIS_PORT=6379; fi

echo "Waiting for DB at $DB_HOST:$DB_PORT..."
until nc -z "$DB_HOST" "$DB_PORT" 2>/dev/null; do
  sleep 1
done
echo "DB is reachable."

echo "Waiting for Redis at $REDIS_HOST:$REDIS_PORT..."
until nc -z "$REDIS_HOST" "$REDIS_PORT" 2>/dev/null; do
  sleep 1
done
echo "Redis is reachable."

echo "All services ready."
```

---

## Makefile

```makefile
.PHONY: install migrate downgrade test lint dev clean help

install:
	cd backend && pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install

migrate:
	cd backend && alembic upgrade head

downgrade:
	cd backend && alembic downgrade -1

test:
	cd backend && pytest -v

lint:
	cd backend && ruff check --fix .
	cd frontend && npm run lint

dev:
	docker-compose up --build

down:
	docker-compose down

logs:
	docker-compose logs -f

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf backend/.pytest_cache backend/.ruff_cache
	docker-compose down -v

help:
	@echo "Available targets:"
	@echo "  make install    - Install Python and Node dependencies"
	@echo "  make migrate    - Run Alembic migrations (upgrade)"
	@echo "  make downgrade  - Rollback last Alembic migration"
	@echo "  make test       - Run pytest"
	@echo "  make lint       - Run ruff and npm linters"
	@echo "  make dev        - Start all services with docker-compose"
	@echo "  make down       - Stop all services"
	@echo "  make logs       - Tail service logs"
	@echo "  make clean      - Clean build artifacts, cache, and containers"
```

---

## CI Pipeline (GitHub Actions)

### `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: workflow_automator_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt -r requirements-dev.txt

      - name: Lint with ruff check
        run: |
          cd backend
          ruff check .

      - name: Format check with ruff format
        run: |
          cd backend
          ruff format --check .

      - name: Run migrations on test DB
        env:
          ALEMBIC_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/workflow_automator_test
          SUPABASE_POOLED_URL: postgresql://postgres:postgres@localhost:5432/workflow_automator_test
          REDIS_URL: redis://localhost:6379
          JWT_SECRET: test-secret
        run: |
          cd backend
          alembic upgrade head

      - name: Run tests
        env:
          DATABASE_TEST_URL: postgresql://postgres:postgres@localhost:5432/workflow_automator_test
          SUPABASE_POOLED_URL: postgresql://postgres:postgres@localhost:5432/workflow_automator_test
          REDIS_URL: redis://localhost:6379
          JWT_SECRET: test-secret
        run: |
          cd backend
          pytest -v --asyncio-mode=auto

```

### Key Points

- **Throwaway Postgres service:** Spun up for each CI run. No access to real Supabase project.
- **Throwaway Redis service:** For testing async Redis operations.
- **DATABASE_TEST_URL set to localhost:** Conftest.py uses allowlist and aborts pytest if empty or not in allowlist.
- **ALEMBIC_DATABASE_URL override:** CI sets this to the test database, so migrations run there instead of production.
- **Migrations tested:** `alembic upgrade head` runs on the test DB to catch schema errors.
- **Ruff lint + format check:** Fail fast on style issues before running tests.
- **`--asyncio-mode=auto`:** Pytest-asyncio mode for async test functions.

---

## Alembic Configuration

### `backend/alembic/env.py`

Alembic uses the direct connection URL by default, but accepts an override for testing:

```python
import os
import asyncio
from sqlalchemy import engine_from_config, pool
from alembic import context
from alembic.config import Config

# Get database URL: prefer ALEMBIC_DATABASE_URL for testing, fall back to SUPABASE_DIRECT_URL
database_url = os.getenv(
    "ALEMBIC_DATABASE_URL",
    os.getenv("SUPABASE_DIRECT_URL")
)

if not database_url:
    raise ValueError(
        "ALEMBIC_DATABASE_URL or SUPABASE_DIRECT_URL must be set."
    )

# Convert to asyncpg driver
database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

config = context.config
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = None  # Import your declarative base here


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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.begin() as connection:
        await connection.run_sync(do_run_migrations)


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

### Usage

**Local development (uses SUPABASE_DIRECT_URL):**
```bash
make migrate          # alembic upgrade head
make downgrade        # alembic downgrade -1
```

**CI (uses ALEMBIC_DATABASE_URL override):**
```bash
ALEMBIC_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/workflow_automator_test \
alembic upgrade head
```

### Key Points

- **ALEMBIC_DATABASE_URL override:** If set, migrations run against this database (used in CI).
- **Falls back to SUPABASE_DIRECT_URL:** For local development.
- **NullPool:** No connection pooling for migrations.

---

## Testing Setup (conftest.py)

```python
import os
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import async_sessionmaker

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
```

### Key Points

- **DATABASE_TEST_URL required:** Aborts pytest if not set.
- **Allowlist guard:** Checks against `localhost`, `127.0.0.1`, or CI service host. Rejects `supabase.co`.
- **Async session maker:** Uses `async_sessionmaker` for async test fixtures.
- **Prevents accidental Supabase writes:** CI and local tests are isolated.

---

## .gitignore

```
# Environment
.env
.env.local
.env.*.local

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
.pytest_cache/
.ruff_cache/
*.egg-info/
.venv/
venv/

# Node
node_modules/
npm-debug.log
yarn-error.log
.next/
out/

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Docker
.docker/
```

---

## README.md (Phase 1 Minimal)

```markdown
# AI-Powered Workflow Automator

A Zapier-like platform where users build visual pipelines and LLM steps process files asynchronously.

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy 2.0 (async), Alembic
- **Database:** Supabase (managed Postgres)
- **Queue:** Celery + Redis
- **Frontend:** Next.js, React, React Flow (pipeline builder)
- **AI:** Anthropic Claude API
- **DevOps:** Docker, docker-compose, GitHub Actions

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- Docker + docker-compose
- Supabase project (free tier OK)

### Setup

1. **Clone and install:**
   ```bash
   git clone <repo>
   cd AI-Powered-Workflow-Automator
   make install
   ```

2. **Configure `.env`:**
   ```bash
   cp backend/.env.example .env
   # Edit .env with your Supabase URLs (direct + pooled), Redis URL, and JWT secret
   ```

3. **Run migrations:**
   ```bash
   make migrate
   ```

4. **Start development services:**
   ```bash
   make dev
   ```

   Services start on:
   - API: http://localhost:8000
   - Frontend: http://localhost:3000
   - Health check: http://localhost:8000/health

### Common Commands

- `make test` — Run pytest
- `make lint` — Format and check code with ruff
- `make downgrade` — Rollback last migration
- `make clean` — Remove build artifacts and containers

## Architecture

**Phase 1 (Foundation):**
- Project scaffold, Docker setup, Supabase connection
- 7-table schema with Row Level Security
- Health check endpoint
- CI with lint + tests

**Phases 2–9:** Auth, pipelines CRUD, file upload, job execution, LLM extraction, validation, frontend, evaluation, deployment.

## Troubleshooting

**Migrations not running?**
- Check `SUPABASE_DIRECT_URL` is reachable (may need session-pooler URL for IPv4).
- Run `make migrate` manually; compose does not auto-migrate.

**"prepared statement X not found" errors?**
- Ensure `SUPABASE_POOLED_URL` has `statement_cache_size=0` in the connection string.

**Redis connection failed?**
- Verify `REDIS_URL` and `docker-compose up` logs.

## Testing

Tests run in CI against a throwaway Postgres container. Locally, set `DATABASE_TEST_URL` to a test database (not Supabase).

```bash
make test
```

## Evaluation & Benchmarks

(Phase 7) Eval harness script computes field-level accuracy, valid-first-attempt rate, latency, and cost.

## Deployment

(Phase 9) See deployment notes for Render, Railway, and Vercel.

---

**Status:** Phase 1 (scaffold + schema) in progress.
```

---

## Pre-commit Configuration

### `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

Install with:
```bash
pip install pre-commit
pre-commit install
```

---

## Success Criteria (Phase 1)

- ✓ `docker-compose up` starts all services (api, worker, redis, frontend)
- ✓ `GET /health` returns `{"status": "ok", "db": "connected", "redis": "connected"}`
- ✓ `make migrate` applies all 7-table schema to Supabase
- ✓ `make downgrade` reverses the last migration
- ✓ `make test` passes on local test DB
- ✓ CI runs ruff lint + pytest on throwaway Postgres, fails on any error
- ✓ `.env.example` documents all config; real `.env` is git-ignored
- ✓ README lets someone clone, `.env`, `make migrate`, `make dev` and see health check
- ✓ All tables have RLS enabled
- ✓ Pooled connection uses `statement_cache_size=0` for PgBouncer compatibility
- ✓ Conftest.py aborts pytest if `DATABASE_TEST_URL` is a Supabase host

---

## Next Phase

Phase 2: Auth endpoints (register, login, refresh) with JWT tokens and bcrypt hashing.
