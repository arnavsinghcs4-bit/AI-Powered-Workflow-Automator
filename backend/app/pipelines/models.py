"""Pipeline execution models: Pipeline, PipelineVersion, Run, StepRun.

Phase 3 replaces the old jobs/pipeline_steps/llm_calls tables. RLS is
enabled on all four tables; the worker deliberately does not set app.user,
so RLS is a no-op there — owner scoping is enforced by the API layer.
"""


import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models import Base


class Pipeline(Base):
    """A named collection of pipeline versions owned by a user."""

    __tablename__ = "pipelines"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    # FK added in a deferred ALTER after pipeline_versions exists; ORM side
    # uses use_alter=True + post_update so the object graph works pre-flush.
    current_version_id = Column(
        Integer,
        ForeignKey("pipeline_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    user = relationship("User", back_populates="pipelines")
    versions = relationship(
        "PipelineVersion", back_populates="pipeline", cascade="all, delete-orphan"
    )
    runs = relationship("Run", back_populates="pipeline", cascade="all, delete-orphan")
    current_version = relationship(
        "PipelineVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )


class PipelineVersion(Base):
    """An immutable snapshot of a pipeline definition."""

    __tablename__ = "pipeline_versions"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "version_number", name="uq_pipeline_versions"),
    )

    id = Column(Integer, primary_key=True)
    pipeline_id = Column(
        Integer,
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    definition = Column(JSON, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    pipeline = relationship(
        "Pipeline", back_populates="versions", foreign_keys=[pipeline_id]
    )
    runs = relationship("Run", back_populates="version")


class Run(Base):
    """A single execution of a pipeline version."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'canceled')",
            name="ck_runs_status",
        ),
        CheckConstraint(
            "trigger_type IN ('manual', 'schedule', 'webhook')",
            name="ck_runs_trigger_type",
        ),
    )

    id = Column(Integer, primary_key=True)
    pipeline_id = Column(
        Integer,
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        Integer,
        ForeignKey("pipeline_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = Column(String(50), server_default="pending", nullable=False, index=True)
    trigger_type = Column(String(50), server_default="manual", nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    error = Column(Text)
    created_at = Column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    pipeline = relationship(
        "Pipeline", back_populates="runs", foreign_keys=[pipeline_id]
    )
    version = relationship("PipelineVersion", foreign_keys=[version_id])
    user = relationship("User", foreign_keys=[user_id])
    step_runs = relationship(
        "StepRun", back_populates="run", cascade="all, delete-orphan"
    )


class StepRun(Base):
    """One node's execution within a run. Retried in place: attempt bumps."""

    __tablename__ = "step_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_step_runs_status",
        ),
        UniqueConstraint("run_id", "node_id", name="uq_step_runs_run_node"),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(
        Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id = Column(String(255), nullable=False)
    step_type = Column(String(50), nullable=False)
    status = Column(String(50), server_default="pending", nullable=False)
    attempt = Column(Integer, server_default="1", nullable=False)
    input = Column(JSON)
    output = Column(JSON)
    error = Column(Text)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))

    run = relationship("Run", back_populates="step_runs", foreign_keys=[run_id])
