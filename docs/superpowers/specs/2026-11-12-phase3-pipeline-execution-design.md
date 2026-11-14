# Phase 3: Pipeline Execution Engine — Design

Date: 2026-11-12
Status: Approved by user (decisions recorded inline)

## Intent

An authenticated user can create a linear two-step pipeline (`http_request` →
`transform`) via API, trigger a run, and poll per-step status and outputs.
Success, failure, retry, timeout and idempotent-redelivery paths are all covered
by passing tests. Backend only; no frontend yet.

## Decisions (from user, 2026-11-12)

1. **Fresh build.** Do NOT edit migration 001. New migration 003 drops the old
   `jobs`, `pipeline_steps`, `step_runs`, `llm_calls` tables and creates the new
   `pipelines` / `pipeline_versions` / `runs` / `step_runs`. Re-add `llm_calls`
   in Phase 4. Checked: no FKs point from `files` into any dropped table
   (`jobs.file_id → files.id` is the reverse direction), so the drop is clean.
2. **`pipelines.current_version_id`**: nullable, `ON DELETE SET NULL`, added via
   deferred `ALTER TABLE` after both tables exist; ORM uses `use_alter=True`
   + `post_update`.
3. **Transform mapping**: `{output_key: template}` reusing the resolver. A lone
   `{{...}}` preserves JSON type (no string coercion).
4. **Enums**: `trigger_type` and `status` are Python `enum.Enum` stored as
   `VARCHAR` (`native_enum=False`). Only `manual` for now.
5. **No real-worker integration test.** Redelivery tested by calling the task
   twice directly. Integration marker deferred.
6. **`updated_at`**: application-set (`server_default=now()` + `onupdate`).
7. **Idempotency**: atomic claim `UPDATE runs SET status='running' WHERE
   id=? AND status='pending' RETURNING id`. `step_runs` gets
   `UNIQUE(run_id, node_id)`; `attempt` updated in place on retry. Stale-run
   recovery documented.
8. **Retry policy**: only network errors, timeouts, 5xx, 408, 429. Fail fast on
   config / SSRF / template / 4xx.
9. **SSRF**: pin the validated IP when connecting; re-validate every redirect
   hop.
10. **Worker DB role**: worker uses the **sync** engine (`get_sync_engine`,
    `prepare_threshold=None`) and runs **outside RLS** (no `app.user` GUC set).
    Owner scoping is enforced by the API layer; worker trust is bounded by
    SSRF + secret redaction + input validation.
11. **Per-step execution**: `asyncio.run` per step inside the Celery worker's
    sync loop; engine + session created per `asyncio.run` with `NullPool`.
12. **Pipeline delete**: explicit cascade in migration — `pipelines` →
    `pipeline_versions` and `runs` → `step_runs` (`ON DELETE CASCADE`).
    `runs.version_id` is `ON DELETE SET NULL` (keep run history if a version is
    dropped).

## Files

### New
- `backend/app/pipelines/models.py` — `Pipeline`, `PipelineVersion`, `Run`,
  `StepRun`
- `backend/app/pipelines/schemas.py` — request/response DTOs, pagination
- `backend/app/pipelines/routes.py` — CRUD + runs endpoints
- `backend/app/steps/__init__.py`, `base.py`, `registry.py`, `resolver.py`,
  `http_request.py`, `transform.py`
- `backend/app/execution/engine.py` — Celery task + step loop
- `backend/app/execution/serializers.py` — secret redaction
- `backend/app/execution/logging.py` — structured logger (run_id, step_run_id)
- `backend/app/execution/ssrf.py` — DNS-resolved blocklist
- `backend/alembic/versions/003_add_pipeline_execution.py`
- `backend/tests/test_resolver.py`, `test_steps.py`, `test_ssrf.py`,
  `test_pipelines_api.py`, `test_engine.py`

### Edit
- `backend/app/models.py` — remove `Pipeline`, `PipelineStep`, `Job`, `StepRun`,
  `LLMCall`; keep `User`, `File`, `RefreshToken`
- `backend/app/main.py` — register pipelines router
- `backend/app/pipelines/__init__.py` — export router

Migration 001 is **not** edited (decision 1: fresh build). The old tables are
dropped in migration 003 alongside the new ones, so upgrade-from-scratch and
the model agree.

## Schema

```
pipelines (id PK, user_id FK→users CASCADE, name, description,
           current_version_id FK→pipeline_versions SET NULL, updated_at)
pipeline_versions (id PK, pipeline_id FK→pipelines CASCADE,
                   version_number INT, definition JSONB, created_at)
                   UNIQUE(pipeline_id, version_number)
runs (id PK, pipeline_id FK→pipelines CASCADE, version_id FK→pipeline_versions
      SET NULL, user_id FK→users CASCADE, status VARCHAR, trigger_type VARCHAR,
      started_at, finished_at, error, created_at)
step_runs (id PK, run_id FK→runs CASCADE, node_id, step_type VARCHAR,
           status VARCHAR, attempt INT, input JSONB, output JSONB, error,
           started_at, finished_at)
           UNIQUE(run_id, node_id)
```

All four tables `ENABLE ROW LEVEL SECURITY`.

## Security

**RLS is a no-op in the worker.** The worker connects via the sync engine
(`get_sync_engine`, `prepare_threshold=None`) and never sets the `app.user`
Postgres GUC, so row-level-security policies evaluate to "no rows visible" →
"all rows visible" depending on the policy's `USING` clause, but with no
`app.user` set the policies cannot match any row and the worker sees every row
it is granted by the DB role. It therefore runs **outside RLS entirely**.

**Owner scoping is enforced by the API layer, not the DB.** The API reads the
run's `user_id` from the row and rejects cross-user access. The worker is
trusted only in the ways that are bounded and auditable:

- **SSRF** — DNS-resolved blocklist; the validated IP is pinned on connect and
  re-validated on every redirect hop (decision 9).
- **Secret redaction** — step outputs and logs pass through
  `execution/serializers.py` before being persisted or emitted.
- **Input validation** — pipeline definitions, templates and step config are
  validated before execution (fail fast on config / template errors, decision 8).
- **Least privilege** — the worker DB role is not a superuser; it has only the
  permissions the app needs.

This is a deliberate trade: RLS would be strictly safer, but the Celery worker
runs in a sync process outside the async API's request context where the
`app.user` GUC would have to be set per-connection and held for the whole task.
The API-layer check is the control, and the worker's blast radius is bounded by
the three items above. If RLS-on-worker is ever required, the change is: set
`app.user = <run.user_id>` on the worker's per-step session before each query.

## Stale-run recovery

A run can be left in `running` state by a worker crash, a killed Celery task,
or a lost `ack` — the atomic claim (decision 7) only flips `pending` →
`running`, so nothing re-claims it automatically.

**Recovery path:** a run whose `status='running'` and `started_at` is older
than the timeout window is treated as stale. Any caller (API or worker) may
re-claim it with the same atomic statement:

```sql
UPDATE runs SET status='pending', started_at=NULL
WHERE id=? AND status='running' AND started_at < (now() - interval '5 minutes')
RETURNING id;
```

`RETURNING id` makes the claim idempotent: two recovery attempts against the
same stale run both see one row only if they serialize correctly, and the
loser sees zero rows and moves on. `step_runs` for the run are left as-is —
their `attempt` counter is what makes a retry safe (decision 7). A re-claimed
run re-executes from step one; already-`succeeded` step_runs are skipped via
`WHERE status != 'succeeded'` in the step loop.

**Not covered:** runs lost mid-step with a partial `step_runs` row in
`running` state. Those rows are reset to `pending` by the same re-claim, so a
retry re-executes the step. There is no checkpointing; a long step that dies
after writing its output but before marking `succeeded` re-runs on recovery.
Acceptable for Phase 3 — checkpointing is a Phase 4+ concern.

## Null `version_id` failure behavior

`runs.version_id` is `ON DELETE SET NULL` (decision 12): dropping a
`pipeline_versions` row keeps the run's history but clears its pointer.

**When a run is triggered against a version that has since been deleted**, the
API resolves the version at trigger time and returns 409/404 — the run is not
created. The `version_id` column is only ever null when a version was deleted
*after* the run started, so a run with `version_id IS NULL` is always a
run whose version was dropped mid-flight.

**API behavior on read:** listing runs joins `pipeline_versions` with
`LEFT JOIN`, so a null `version_id` renders as `version: null` rather than
hiding the run. The run's `pipeline_id` is never null (it is `NOT NULL` with
`ON DELETE CASCADE`), so the run is always attributable to a pipeline and its
owner.

## Open questions (settled by user — recorded for the builder)

None outstanding. All six questions from the initial plan were answered in the
decisions above.