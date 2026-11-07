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
   cp .env.example .env
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
- `make format-check` — Check ruff format without changes
- `make downgrade` — Rollback last migration
- `make clean` — Remove build artifacts and containers

## Architecture

### Phase 1 (Current): Foundation
- Project scaffold, Docker setup, Supabase connection
- 7-table schema with Row Level Security
- Health check endpoint
- CI with lint + tests

### Database Schema

**7 Tables:**
- `users` — User accounts (email, password_hash)
- `pipelines` — User-created pipelines (soft-delete via is_active=false)
- `pipeline_steps` — Steps within a pipeline (type, config)
- `files` — Uploaded files (Supabase Storage references)
- `jobs` — Pipeline executions (status, idempotency_key)
- `step_runs` — Individual step executions (input, output, attempt)
- `llm_calls` — LLM API call logs (tokens, cost, latency)

**Key Features:**
- Row Level Security (RLS) enabled on all tables; REST roles (anon, authenticated) revoked
- Soft-delete on pipelines: set `is_active=false` in API, hard cascade only for user deletion
- `step_runs.step_id` uses `ON DELETE SET NULL` to preserve audit trail
- All timestamps use TIMESTAMPTZ (UTC)
- CHECK constraints on status columns for database-level validation
- Idempotency keys on jobs for duplicate prevention

### Reliability

- Connection pooling: `statement_cache_size=0` for PgBouncer compatibility
- Health check verifies DB and Redis connectivity; returns 503 when degraded
- JWT_SECRET validation: refuses to start in production if placeholder is unchanged
- Migrations reversible: `make migrate` / `make downgrade`

## Testing

Tests run in CI against a throwaway Postgres container. Locally, set `DATABASE_TEST_URL` to a test database (not Supabase).

```bash
make test
```

Safety guard aborts pytest if `DATABASE_TEST_URL` is empty or contains `supabase.co`.

## Troubleshooting

**Migrations not running?**
- Check `SUPABASE_DIRECT_URL` is reachable.
- Run `make migrate` manually; compose does not auto-migrate.

**"prepared statement X not found" errors?**
- Ensure `SUPABASE_POOLED_URL` has `prepared_statement_cache_size=0` in the connection string.
- Check `backend/scripts/pooler_check.py` for connection pooling validation.

**Redis connection failed?**
- Verify `REDIS_URL` and `docker-compose up` logs.

## Next Phases

- **Phase 2:** Auth (register, login, refresh)
- **Phase 3:** Pipelines CRUD + file upload
- **Phase 4:** Celery job execution
- **Phase 5:** LLM extraction with validation + retries
- **Phase 6:** Validate, send_email, webhook steps + rate limiting
- **Phase 7:** Evaluation harness
- **Phase 8:** Frontend
- **Phase 9:** Deployment

---

**Status:** Phase 1 (scaffold + schema) complete.
