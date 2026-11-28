"""Credentials models for Phase 4 secrets management."""

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models import Base


class CredentialKind(str):
    """Credential kind enumeration stored as VARCHAR."""
    API_KEY = "api_key"
    SMTP = "smtp"
    BEARER = "bearer"
    BASIC = "basic"


class Credential(Base):
    """User credential stored encrypted at rest."""

    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_credentials_user_name"),
        CheckConstraint(
            "kind IN ('api_key', 'smtp', 'bearer', 'basic')",
            name="ck_credentials_kind",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(255), nullable=False)
    kind = Column(String(50), nullable=False)
    encrypted_value = Column(LargeBinary(), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="credentials")


class LLMCall(Base):
    """Record of an LLM call for token budget tracking."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'rate_limited')",
            name="ck_llm_calls_status",
        ),
        Index("idx_llm_calls_step_run_id", "step_run_id"),
        Index("idx_llm_calls_user_id", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    step_run_id = Column(
        Integer, ForeignKey("step_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    latency_ms = Column(Integer)
    status = Column(String(50), server_default="succeeded", nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )