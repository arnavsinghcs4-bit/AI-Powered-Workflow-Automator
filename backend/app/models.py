"""SQLAlchemy models."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """User model."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    pipelines = relationship(
        "Pipeline", back_populates="user", cascade="all, delete-orphan"
    )
    files = relationship("File", back_populates="user", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )


class Pipeline(Base):
    """Pipeline model."""

    __tablename__ = "pipelines"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="pipelines")
    steps = relationship(
        "PipelineStep", back_populates="pipeline", cascade="all, delete-orphan"
    )
    jobs = relationship("Job", back_populates="pipeline", cascade="all, delete-orphan")


class PipelineStep(Base):
    """Pipeline step model."""

    __tablename__ = "pipeline_steps"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "position", name="uq_pipeline_steps_position"),
        CheckConstraint(
            "type IN ('extract_text', 'llm_extract', 'validate', 'send_email', 'webhook')",
            name="ck_pipeline_steps_type",
        ),
    )

    id = Column(Integer, primary_key=True)
    pipeline_id = Column(
        Integer,
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    type = Column(String(50), nullable=False)
    config = Column(JSON, default={}, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    pipeline = relationship("Pipeline", back_populates="steps")
    step_runs = relationship("StepRun", back_populates="step")


class File(Base):
    """Uploaded file model."""

    __tablename__ = "files"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(255), nullable=False)
    mime_type = Column(String(100))
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="files")
    jobs = relationship("Job", back_populates="file", cascade="all, delete-orphan")


class Job(Base):
    """Job (pipeline run) model."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'needs_review')",
            name="ck_jobs_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pipeline_id = Column(
        Integer,
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id = Column(
        Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = Column(String(50), default="queued", nullable=False, index=True)
    error = Column(Text)
    idempotency_key = Column(String(255), unique=True, index=True)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="jobs")
    pipeline = relationship("Pipeline", back_populates="jobs")
    file = relationship("File", back_populates="jobs")
    step_runs = relationship(
        "StepRun", back_populates="job", cascade="all, delete-orphan"
    )


class StepRun(Base):
    """Step run (step execution within a job) model."""

    __tablename__ = "step_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_step_runs_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id = Column(
        Integer, ForeignKey("pipeline_steps.id", ondelete="SET NULL"), index=True
    )
    status = Column(String(50), nullable=False)
    input = Column(JSON)
    output = Column(JSON)
    error = Column(Text)
    attempt = Column(Integer, default=1, nullable=False)
    duration_ms = Column(Integer)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    job = relationship("Job", back_populates="step_runs")
    step = relationship("PipelineStep", back_populates="step_runs")
    llm_calls = relationship(
        "LLMCall", back_populates="step_run", cascade="all, delete-orphan"
    )


class LLMCall(Base):
    """LLM API call log."""

    __tablename__ = "llm_calls"

    id = Column(Integer, primary_key=True)
    step_run_id = Column(
        Integer,
        ForeignKey("step_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model = Column(String(100), nullable=False)
    prompt = Column(Text, nullable=False)
    response = Column(Text)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    cost_usd = Column(Numeric(10, 6))
    latency_ms = Column(Integer)
    valid_json = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    step_run = relationship("StepRun", back_populates="llm_calls")


class RefreshToken(Base):
    """Refresh token model for token rotation and revocation."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="refresh_tokens")
