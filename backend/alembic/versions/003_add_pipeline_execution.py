"""Add pipeline execution engine tables: pipelines / pipeline_versions / runs / step_runs.

Revision ID: 003_add_pipeline_execution
Revises: 002_add_auth_tables
Create Date: 2026-11-12 10:15:00.000000

---
Migration 003 drops the old jobs/pipeline_steps/llm_calls tables and creates the new
pipelines / pipeline_versions / runs / step_runs.  No FKs point from files into
any dropped table (jobs.file_id -> files.id is the reverse direction), so the drop
is clean.

pipelines (id PK, user_id FK CASCADE, name, description,
              current_version_id FK CASCADE SET NULL, updated_at)
pipeline_versions (id PK, pipeline_id FK CASCADE,
                   version_number INT, definition JSONB, created_at)
                   UNIQUE(pipeline_id, version_number)
runs (id PK, pipeline_id FK CASCADE, version_id FK SET NULL,
      user_id FK CASCADE, status VARCHAR, trigger_type VARCHAR,
      started_at, finished_at, error, created_at,
      claimed_at TIMESTAMP(timezone) NULL)
      ENABLE ROW LEVEL SECURITY
step_runs (id PK, run_id FK CASCADE, node_id, step_type VARCHAR,
           status VARCHAR, attempt INT, input JSONB, output JSONB, error,
           started_at, finished_at)
           UNIQUE(run_id, node_id)
           ENABLE ROW LEVEL SECURITY

The runs table includes a claimed_at lease column (NULL = unclaimed).
The worker sets claimed_at when claiming a run; stale-run recovery
clamps on (status='running' AND claimed_at < now() - interval '5 minutes').
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "003_add_pipeline_execution"
down_revision = "002_add_auth_tables"
branch_labels = None
depends_on = None

# Only run REVOKE commands on Supabase (identified by the presence of supabase.co in URL)
database_url = os.getenv("ALEMBIC_DATABASE_URL", os.getenv("SUPABASE_DIRECT_URL", ""))
IS_SUPABASE = "supabase.co" in database_url


def upgrade() -> None:
    """Create new pipeline execution tables + drop old ones."""
    # ---- drop old tables (001 shape), leaf-first so no FK blocks a drop ----
    # llm_calls -> step_runs -> (jobs, pipeline_steps) -> pipelines
    op.drop_index("idx_llm_calls_step_run_id", table_name="llm_calls", if_exists=True)
    op.drop_table("llm_calls")

    op.drop_index("idx_step_runs_job_id", table_name="step_runs", if_exists=True)
    op.drop_index("idx_step_runs_step_id", table_name="step_runs", if_exists=True)
    op.drop_table("step_runs")

    op.drop_index("idx_jobs_user_id", table_name="jobs", if_exists=True)
    op.drop_index("idx_jobs_pipeline_id", table_name="jobs", if_exists=True)
    op.drop_index("idx_jobs_file_id", table_name="jobs", if_exists=True)
    op.drop_index("idx_jobs_status", table_name="jobs", if_exists=True)
    op.drop_index("idx_jobs_idempotency_key", table_name="jobs", if_exists=True)
    op.drop_table("jobs")

    op.drop_index(
        "idx_pipeline_steps_pipeline_id",
        table_name="pipeline_steps",
        if_exists=True,
    )
    op.drop_table("pipeline_steps")

    op.drop_index("idx_pipelines_user_id", table_name="pipelines", if_exists=True)
    op.drop_table("pipelines")

    # ---- create new pipelines (current_version_id FK added deferred) ----
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_pipelines_user_id", "pipelines", ["user_id"])
    op.create_index(
        "idx_pipelines_current_version_id", "pipelines", ["current_version_id"]
    )
    op.execute("ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON pipelines FROM anon, authenticated;")

    # ---- create pipeline_versions ----
    op.create_table(
        "pipeline_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_id", "version_number", name="uq_pipeline_versions"
        ),
    )
    op.create_index(
        "idx_pipeline_versions_pipeline_id", "pipeline_versions", ["pipeline_id"]
    )
    op.execute("ALTER TABLE pipeline_versions ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON pipeline_versions FROM anon, authenticated;")

    # ---- deferred FK: pipelines.current_version_id -> pipeline_versions.id ----
    # Added after both tables exist (decision 2). ORM mirrors this with
    # use_alter=True + post_update.
    op.create_foreign_key(
        "fk_pipelines_current_version_id",
        "pipelines",
        "pipeline_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ---- runs (new) ----
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "trigger_type",
            sa.String(50),
            server_default="manual",
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Lease column. Set by the worker when it claims a run; cleared on
        # re-claim. Stale-run recovery keys off this, NOT off status alone,
        # because a crashed run stays status='running' forever.
        sa.Column("claimed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["pipeline_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'canceled')",
            name="ck_runs_status",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('manual', 'schedule', 'webhook')",
            name="ck_runs_trigger_type",
        ),
    )
    op.create_index("idx_runs_pipeline_id", "runs", ["pipeline_id"])
    op.create_index("idx_runs_version_id", "runs", ["version_id"])
    op.create_index("idx_runs_user_id", "runs", ["user_id"])
    op.create_index("idx_runs_status", "runs", ["status"])
    op.create_index("idx_runs_stale", "runs", ["status", "claimed_at"])
    op.execute("ALTER TABLE runs ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON runs FROM anon, authenticated;")

    # ---- step_runs (new) ----
    op.create_table(
        "step_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("step_type", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempt",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("input", sa.JSON()),
        sa.Column("output", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_step_runs_status",
        ),
        sa.UniqueConstraint("run_id", "node_id", name="uq_step_runs_run_node"),
    )
    op.create_index("idx_step_runs_run_id", "step_runs", ["run_id"])
    op.create_index("idx_step_runs_node_id", "step_runs", ["node_id"])
    op.execute("ALTER TABLE step_runs ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON step_runs FROM anon, authenticated;")


def downgrade() -> None:
    """Drop new tables + re-create old ones (001 shape + RLS)."""
    # ---- drop new tables, leaf-first (FKs) ----
    op.drop_index("idx_step_runs_node_id", table_name="step_runs", if_exists=True)
    op.drop_index("idx_step_runs_run_id", table_name="step_runs", if_exists=True)
    op.execute("ALTER TABLE step_runs DISABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON step_runs FROM anon, authenticated;")
    op.drop_table("step_runs")

    op.drop_index("idx_runs_stale", table_name="runs", if_exists=True)
    op.drop_index("idx_runs_status", table_name="runs", if_exists=True)
    op.drop_index("idx_runs_user_id", table_name="runs", if_exists=True)
    op.drop_index("idx_runs_version_id", table_name="runs", if_exists=True)
    op.drop_index("idx_runs_pipeline_id", table_name="runs", if_exists=True)
    op.execute("ALTER TABLE runs DISABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON runs FROM anon, authenticated;")
    op.drop_table("runs")

    op.drop_index(
        "idx_pipeline_versions_pipeline_id",
        table_name="pipeline_versions",
        if_exists=True,
    )
    op.execute("ALTER TABLE pipeline_versions DISABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON pipeline_versions FROM anon, authenticated;")

    # Drop FK constraint on pipelines pointing to pipeline_versions
    op.drop_constraint(
        "fk_pipelines_current_version_id", "pipelines", type_="foreignkey"
    )
    op.drop_index(
        "idx_pipelines_current_version_id",
        table_name="pipelines",
        if_exists=True,
    )
    op.execute("ALTER TABLE pipelines DISABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON pipelines FROM anon, authenticated;")
    op.drop_index("idx_pipelines_user_id", table_name="pipelines", if_exists=True)

    # Now drop pipeline_versions (after FK removed from pipelines)
    op.drop_table("pipeline_versions")

    # Now drop pipelines
    op.drop_table("pipelines")

    # ---- re-create old tables in 001 shape ----
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_pipelines_user_id", "pipelines", ["user_id"])
    op.execute("ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON pipelines FROM anon, authenticated;")

    op.create_table(
        "pipeline_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("config", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('extract_text', 'llm_extract', 'validate', 'send_email', 'webhook')",
            name="ck_pipeline_steps_type",
        ),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_id", "position", name="uq_pipeline_steps_position"
        ),
    )
    op.create_index("idx_pipeline_steps_pipeline_id", "pipeline_steps", ["pipeline_id"])
    op.execute("ALTER TABLE pipeline_steps ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON pipeline_steps FROM anon, authenticated;")

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), server_default="queued", nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'needs_review')",
            name="ck_jobs_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("idx_jobs_user_id", "jobs", ["user_id"])
    op.create_index("idx_jobs_pipeline_id", "jobs", ["pipeline_id"])
    op.create_index("idx_jobs_file_id", "jobs", ["file_id"])
    op.create_index("idx_jobs_status", "jobs", ["status"])
    op.create_index("idx_jobs_idempotency_key", "jobs", ["idempotency_key"])
    op.execute("ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON jobs FROM anon, authenticated;")

    op.create_table(
        "step_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.Integer()),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("input", sa.JSON()),
        sa.Column("output", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_step_runs_status",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["step_id"], ["pipeline_steps.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_step_runs_job_id", "step_runs", ["job_id"])
    op.create_index("idx_step_runs_step_id", "step_runs", ["step_id"])
    op.execute("ALTER TABLE step_runs ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON step_runs FROM anon, authenticated;")

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("step_run_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("cost_usd", sa.Numeric(10, 6)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("valid_json", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["step_run_id"], ["step_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_llm_calls_step_run_id", "llm_calls", ["step_run_id"])
    op.execute("ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON llm_calls FROM anon, authenticated;")

    # users table already exists; just ensure its index + RLS are restored
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON users FROM anon, authenticated;")
