"""Add refresh tokens table for authentication."""

import os

import sqlalchemy as sa

from alembic import op

revision = "002_add_auth_tables"
down_revision = "001_init_schema"
branch_labels = None
depends_on = None

# Only run REVOKE commands on Supabase (identified by the presence of supabase.co in URL)
database_url = os.getenv("ALEMBIC_DATABASE_URL", os.getenv("SUPABASE_DIRECT_URL", ""))
IS_SUPABASE = "supabase.co" in database_url


def upgrade() -> None:
    """Create refresh_tokens table."""
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("idx_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("idx_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;")
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON refresh_tokens FROM anon, authenticated;")


def downgrade() -> None:
    """Drop refresh_tokens table."""
    if IS_SUPABASE:
        op.execute("REVOKE ALL ON refresh_tokens FROM anon, authenticated;")
    op.drop_index("idx_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("idx_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
