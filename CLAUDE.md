# AI-Powered Workflow Automator - Development Workflow

This document configures Claude Code for efficient development on this FastAPI + Next.js project.

## Project Overview
- **Backend**: FastAPI async API, SQLAlchemy 2.0 ORM, Supabase PostgreSQL, Celery workers, Redis
- **Frontend**: Next.js with React Flow for workflow builder
- **Phase**: Currently in Phase 1 (core infrastructure). Phase 2 is authentication (JWT + bcrypt).

## Plugin Activation Rules

### 1. **Superpowers** (Brainstorming, Planning, Debugging)
**Trigger**: When the user describes:
- A new feature or major refactor ("add JWT authentication", "redesign the worker system")
- A multi-step problem ("fix the migration errors", "debug why tests fail")
- Complex architectural decisions ("how should we handle RLS?")

**Action**: Invoke `/superpowers:brainstorming` or `/superpowers:systematic-debugging` before implementation.

**Why**: Prevents false starts, surfaces hidden complexity, ensures proper design before coding.

### 2. **Code Review** (Correctness & Security)
**Trigger**: Before merging major features or after security-sensitive changes:
- Authentication/authorization code
- Database access patterns
- API endpoint changes
- Changes to config or dependency injection

**Action**: Run `/code-review high --fix` on changed files to catch bugs and security issues.

**Why**: Catches edge cases, SQL injection risks, async/await issues, and improves code quality.

### 3. **Context7** (Framework & Library Docs)
**Trigger**: When working with unfamiliar or complex libraries:
- SQLAlchemy async patterns ("how do I use async context managers correctly?")
- FastAPI dependency injection and middleware
- Pydantic validation patterns
- Next.js/React Flow integration questions

**Action**: Automatically consulted; no explicit trigger needed. Use `/claude-api` for Claude model questions.

**Why**: Ensures patterns match current best practices and library versions.

### 4. **Graphify** (Code Understanding & Architecture)
**Trigger**: When understanding unfamiliar code or analyzing dependencies:
- "How do the database, config, and health check relate?"
- "What does this migration do and how does it connect to models?"
- "Map out the auth flow"

**Action**: Invoke `/graphify` to visualize code relationships and data flow.

**Why**: Clarifies complex interactions, especially useful when jumping between files.

### 5. **Security Review** (Auth, Secrets, Access Control)
**Trigger**: Automatic for any changes involving:
- Authentication (JWT, bcrypt, session handling)
- Authorization (RLS, permission checks)
- Secrets or credentials
- Database row-level security

**Action**: Invoke `/security-review` after code changes to auth/sensitive systems.

**Why**: Prevents authentication bypass, credential leaks, and authorization flaws.

### 6. **Frontend Design** (UI/UX Changes)
**Trigger**: When building or modifying React components:
- Workflow builder UI in React Flow
- Forms, dashboards, settings pages
- Component layout or styling changes

**Action**: Load `/frontend-design` before writing component code.

**Why**: Ensures consistent design, accessibility, and responsive layouts.

## Testing & Verification

### After Every Code Change
```bash
# Lint and format
make lint

# Run tests (if modifying backend logic)
cd backend && pytest -v

# Type check (Python)
cd backend && python -m mypy app --ignore-missing-imports || true
```

### Before Committing Major Features
```bash
# Full verification
make clean
make lint
cd backend && pytest -v --cov=app
```

### Pre-Commit Hook (Optional)
```bash
cd <project-root>
pip install pre-commit
pre-commit install
```

The `.pre-commit-config.yaml` is already configured with ruff checks.

## Workflow by Phase

## Current status
Phases 1-2 complete. Phase 3 (pipeline execution engine) in progress on a feature branch. See docs/phase3.md.

## Working rules
- Once a plan is approved, execute the whole task list without pausing. Stop only for: destructive actions on a real database, a test still failing after two fix attempts, or a spec/codebase contradiction.
- Explicit user instructions override plugin workflow gates (brainstorming, VibeWise, etc.).
- For multi-step work, create a task list first. Include docs as deliverables. Mark done only after verifying.
- Never report a file as written, edited or deleted unless verified this session (ls, Read, git status). After a restart, re-verify the ledger against disk.
- Final summaries must list tests executed vs. written-but-unexecuted.

## Safety
- Never run tests against Supabase; never loosen the DATABASE_TEST_URL guard.
- Flag any migration that drops tables before running it anywhere but a throwaway DB. Never edit an applied migration.
- Never read or print .env. Never log or persist secrets.
- Work on a branch, small commits, never commit to main, don't push unless asked.

## Environment
Shell is Windows PowerShell 5.1: use `;` not `&&`. Activate venv with .\.venv\Scripts\Activate.ps1. Run Python and pytest from backend/.

## Architecture decisions
- Linear pipelines only (JSONB graph definition, React Flow compatible).
- Run claim is atomic: UPDATE ... WHERE status='pending' RETURNING; claimed_at lease for stale recovery.
- Worker uses the sync engine and runs outside RLS; API enforces owner scoping and returns 404 for other users' resources.
- Status/trigger columns are VARCHAR, not native enums.
- http_request: SSRF protection pins the validated IP and re-validates every redirect hop.

## Plugin triggers (explicit, not automatic)
- /security-review: before committing auth, secrets, RLS or SSRF changes.
- /code-review: before opening a PR. Review the diff after any --fix.
- /graphify: for architecture questions; run `graphify update .` after large changes.

## File Organization

```
backend/
  app/
    auth/          ← Phase 2: JWT + bcrypt here
      models.py    (User table schema)
      routes.py    (POST /auth/register, /auth/login, /auth/refresh)
      schemas.py   (Request/response schemas)
    health.py      (Liveness probe)
    config.py      (Environment configuration)
    database.py    (Async ORM engine)
    main.py        (FastAPI app factory)
  tests/
    test_auth.py   (Auth endpoint tests, added Phase 2)
  alembic/
    versions/
      002_add_users_auth.py  (User table migration, Phase 2)

frontend/
  app/
    page.tsx       (Home, workflow list)
    layout.tsx     (Navbar, auth state)
  components/
    WorkflowBuilder.tsx  (React Flow visualization, Phase 2+)
```

## Common Tasks

### Add a New Endpoint
1. Define schema in `app/schemas.py`
2. Add route in appropriate module (e.g., `app/pipelines/routes.py`)
3. Write tests in `backend/tests/`
4. Run `make lint` and `/code-review high`

### Modify Database Schema
1. Create migration: `cd backend && alembic revision --autogenerate -m "description"`
2. Edit migration file in `alembic/versions/`
3. Test locally: `alembic upgrade head`
4. Commit and push; CI will apply to test DB

### Deploy to Production
1. Ensure all tests pass: `make test`
2. Review all pending commits: `git log origin/main..HEAD`
3. Push to main: `git push origin main`
4. GitHub Actions CI runs; Docker images pushed to registry

## Environment Variables

### Development (.env)
```
SUPABASE_DIRECT_URL=postgresql://...
SUPABASE_POOLED_URL=postgresql://...
REDIS_URL=redis://redis:6379
JWT_SECRET=dev-key-change-in-production
ENV=dev
```

### CI (GitHub Actions)
Set via repository secrets; see `.github/workflows/ci.yml`.

### Production (Docker)
Environment variables passed at container runtime or via `.env` in deployment.

## Troubleshooting

**Tests fail with config error**: Ensure `DATABASE_TEST_URL` is set or tests mock the config.

**Alembic migration fails**: Check that `ALEMBIC_DATABASE_URL` points to a valid test DB; migrations now skip Supabase-specific REVOKE commands on non-Supabase databases.

**Health check returns 500**: Verify `SUPABASE_POOLED_URL` is set and accessible. The endpoint mocks Redis and DB in tests.

**Ruff format check fails in CI**: Run `make lint` locally and commit the formatted code.

## Key Decisions

- **Async-first**: All DB operations are async to leverage FastAPI's performance.
- **Separate engines**: Async engine (API) uses asyncpg; sync engine (worker) uses psycopg with `prepare_threshold=None` for PgBouncer compatibility.
- **RLS on all tables**: Row-level security enforced at the database layer; API enforces user_id checks as defense-in-depth.
- **Migrations for schema**: Alembic tracks all DB changes; migrations run in CI before tests.
- **TDD for features**: New endpoints have tests written first; tests guide the design.

## Questions?

- For framework docs: Use Context7 or `/claude-api`
- For design decisions: Use `/superpowers:brainstorming`
- For security: Use `/security-review`
- For code quality: Use `/code-review high`
- For understanding existing code: Use `/graphify`

Never report a file as written, edited or deleted unless you verified it in this session with a tool call (ls, Read, git status). When resuming after a restart, re-verify every claim in the ledger against the disk before continuing, and correct the ledger where it's wrong.

## Installed plugins
- claude-mem: provides cross-session memory automatically. At the start of a task, check it (mem-search) for prior decisions on that area before asking me to repeat them. Never store secrets, .env contents or DB URLs in memory.
- graphify: for architecture or "how does X connect to Y" questions, query the graph first (read graphify-out/GRAPH_REPORT.md), then read files. Run `graphify update .` after large changes or new modules.
- VibeWise: applies only when I say "teach me" or "walk me through" (or: applies to all work, pick one). It must not block approved tasks or file writes.