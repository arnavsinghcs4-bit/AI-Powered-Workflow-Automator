"""Add credentials and llm_calls tables for Phase 4.

Revision ID: 004_credentials_llm_calls
Revises: 003_add_pipeline_execution
Create Date: 2026-11-15

---
credentials (id PK, user_id FK CASCADE, name VARCHAR UNIQUE per user,
           kind VARCHAR CHECK IN ('api_key', 'smtp', 'bearer', 'basic'),
           encrypted_value BYTEA, created_at, updated_at)
           ENABLE ROW LEVEL SECURITY
           UNIQUE(user_id, name)

llm_calls (id PK, step_run_id FK CASCADE, user_id FK CASCADE,
           provider VARCHAR, model VARCHAR,
           input_tokens INT, output_tokens INT, latency_ms INT,
           status VARCHAR CHECK IN ('succeeded', 'failed', 'rate_limited'),
           created_at)
           ENABLE ROW LEVEL SECURITY
           INDEX(step_run_id)
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "004_credentials_llm_calls"
down_revision = "003_add_pipeline_execution"
branch_labels = None
depends_on = None

# Only run REVOKE commands on Supabase (identified by the presence of supabase.co in URL)
database_url = os.getenv("ALEMBIC_DATABASE_URL", os.getenv("SUPABASE_DIRECT_URL", ""))
IS_SUPABASE = "supabase.co" in database_url


def upgrade() -> None:
    """Create credentials and llm_calls tables."""
    # ---- credentials table ----
    op.create_table(
        "credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "kind",
            sa.String(50),
            nullable=False,
        ),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_credentials_user_name"),
        sa.CheckConstraint(
            "kind IN ('api_key', 'smtp', 'bearer', 'basic')",
            name="ck_credentials_kind",
        ),
    )
    op.create_index("idx_credentials_user_id", "credentials", ["user_id"])
    op.execute("ALTER TABLE credentials ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON credentials FROM anon, authenticated;")

    # ---- llm_calls table ----
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("step_run_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column(
            "status",
            sa.String(50),
            server_default="succeeded",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["step_run_id"], ["step_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'rate_limited')",
            name="ck_llm_calls_status",
        ),
    )
    op.create_index("idx_llm_calls_step_run_id", "llm_calls", ["step_run_id"])
    op.create_index("idx_llm_calls_user_id", "llm_calls", ["user_id"])
    op.execute("ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON llm_calls FROM anon, authenticated;")


def downgrade() -> None:
    """Drop credentials and llm_calls tables."""
    op.drop_index("idx_llm_calls_user_id", table_name="llm_calls", if_exists=True)
    op.drop_index("idx_llm_calls_step_run_id", table_name="llm_calls", if_exists=True)
    op.execute("ALTER TABLE llm_calls DISABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON llm_calls FROM anon, authenticated;")
    op.drop_table("llm_calls")

    op.drop_index("idx_credentials_user_id", table_name="credentials", if_exists=True)
    op.execute("ALTER TABLE credentials DISABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON credentials FROM anon, authenticated;")
    op.drop_table("credentials")