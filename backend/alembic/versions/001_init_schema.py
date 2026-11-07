"""Initial schema with 7 tables and RLS."""
from alembic import op
import sqlalchemy as sa


revision = "001_init_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial schema."""
    # users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("idx_users_email", "users", ["email"])
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY;")
    op.execute("REVOKE ALL ON users FROM anon, authenticated;")

    # pipelines table
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_pipelines_user_id", "pipelines", ["user_id"])
    op.execute("ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;")
    op.execute("REVOKE ALL ON pipelines FROM anon, authenticated;")

    # pipeline_steps table
    op.create_table(
        "pipeline_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("config", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("type IN ('extract_text', 'llm_extract', 'validate', 'send_email', 'webhook')", name="ck_pipeline_steps_type"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_id", "position", name="uq_pipeline_steps_position"),
    )
    op.create_index("idx_pipeline_steps_pipeline_id", "pipeline_steps", ["pipeline_id"])
    op.execute("ALTER TABLE pipeline_steps ENABLE ROW LEVEL SECURITY;")
    op.execute("REVOKE ALL ON pipeline_steps FROM anon, authenticated;")

    # files table
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_files_user_id", "files", ["user_id"])
    op.execute("ALTER TABLE files ENABLE ROW LEVEL SECURITY;")
    op.execute("REVOKE ALL ON files FROM anon, authenticated;")

    # jobs table
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
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'needs_review')", name="ck_jobs_status"),
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
    op.execute("REVOKE ALL ON jobs FROM anon, authenticated;")

    # step_runs table
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
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_step_runs_status"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["pipeline_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_step_runs_job_id", "step_runs", ["job_id"])
    op.create_index("idx_step_runs_step_id", "step_runs", ["step_id"])
    op.execute("ALTER TABLE step_runs ENABLE ROW LEVEL SECURITY;")
    op.execute("REVOKE ALL ON step_runs FROM anon, authenticated;")

    # llm_calls table
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
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["step_run_id"], ["step_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_llm_calls_step_run_id", "llm_calls", ["step_run_id"])
    op.execute("ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY;")
    op.execute("REVOKE ALL ON llm_calls FROM anon, authenticated;")


def downgrade() -> None:
    """Drop all tables."""
    op.execute("REVOKE ALL ON llm_calls FROM anon, authenticated;")
    op.drop_index("idx_llm_calls_step_run_id", table_name="llm_calls")
    op.drop_table("llm_calls")

    op.execute("REVOKE ALL ON step_runs FROM anon, authenticated;")
    op.drop_index("idx_step_runs_job_id", table_name="step_runs")
    op.drop_index("idx_step_runs_step_id", table_name="step_runs")
    op.drop_table("step_runs")

    op.execute("REVOKE ALL ON jobs FROM anon, authenticated;")
    op.drop_index("idx_jobs_user_id", table_name="jobs")
    op.drop_index("idx_jobs_pipeline_id", table_name="jobs")
    op.drop_index("idx_jobs_file_id", table_name="jobs")
    op.drop_index("idx_jobs_status", table_name="jobs")
    op.drop_index("idx_jobs_idempotency_key", table_name="jobs")
    op.drop_table("jobs")

    op.execute("REVOKE ALL ON files FROM anon, authenticated;")
    op.drop_index("idx_files_user_id", table_name="files")
    op.drop_table("files")

    op.execute("REVOKE ALL ON pipeline_steps FROM anon, authenticated;")
    op.drop_index("idx_pipeline_steps_pipeline_id", table_name="pipeline_steps")
    op.drop_table("pipeline_steps")

    op.execute("REVOKE ALL ON pipelines FROM anon, authenticated;")
    op.drop_index("idx_pipelines_user_id", table_name="pipelines")
    op.drop_table("pipelines")

    op.execute("REVOKE ALL ON users FROM anon, authenticated;")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
