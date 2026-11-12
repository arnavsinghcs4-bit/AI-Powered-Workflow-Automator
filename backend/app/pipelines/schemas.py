"""Request/response DTOs and pagination for pipeline CRUD."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field



class PipelineBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class PipelineCreate(PipelineBase):
    pass


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class PipelineInDB(PipelineBase):
    id: int
    user_id: int
    is_active: bool
    current_version_id: int | None
    created_at: Any
    updated_at: Any

    class Config:
        from_attributes = True


class PipelineVersionBase(BaseModel):
    version_number: int = Field(..., ge=1)
    definition: dict[str, Any]


class PipelineVersionCreate(PipelineVersionBase):
    pass


class PipelineVersionInDB(PipelineVersionBase):
    id: int
    pipeline_id: int
    created_at: Any

    class Config:
        from_attributes = True


class RunBase(BaseModel):
    status: str | None = None
    trigger_type: str | None = None


class RunInDB(RunBase):
    id: int
    pipeline_id: int
    version_id: int | None
    user_id: int
    status: str
    trigger_type: str
    started_at: Any | None
    finished_at: Any | None
    error: str | None
    created_at: Any

    class Config:
        from_attributes = True


class StepRunBase(BaseModel):
    status: str | None = None
    attempt: int | None = None


class StepRunInDB(StepRunBase):
    id: int
    run_id: int
    node_id: str
    step_type: str
    status: str
    attempt: int
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: str | None
    started_at: Any | None
    finished_at: Any | None

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    """Create a pipeline run (trigger)."""

    pipeline_id: int = Field(..., gt=0)
    version_id: int | None = None
    trigger_type: str = Field(
        default="manual",
        pattern="^(manual|schedule|webhook)$",
    )
    input_data: dict[str, Any] | None = None


class TaskResponse(BaseModel):
    """Response from triggering a pipeline run."""

    run_id: int
    pipeline_id: int
    version_id: int | None
    status: str
    message: str


class HealthCheck(BaseModel):
    """Response from the /health endpoint."""

    status: str
    db: str
    redis: str


class AuthTokens(BaseModel):
    """Auth response tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordStrength(BaseModel):
    """Password policy for validators."""

    min_length: int = 10
    require_uppercase: bool = False
    require_lowercase: bool = False
    require_digit: bool = True
    require_special: bool = False


# Pagination helpers
class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int = 1
    per_page: int = 20
    total_pages: int = 1