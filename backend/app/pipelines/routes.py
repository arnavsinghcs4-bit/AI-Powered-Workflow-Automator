"""Pipeline CRUD + runs endpoints.

Routes registered under ``app`` with prefix ``/pipelines``.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import config
from app.database import get_session
from app.steps.registry import (
    step_types,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.models import User
from app.pipelines.schemas import (
    PipelineCreate,
    PipelineInDB,
    PipelineVersionBase,
    PipelineVersionInDB,
    TaskCreate,
    TaskResponse,
)
from app.pipelines.service import (
    create_pipeline,
    get_pipeline,
    list_pipelines,
    trigger_run,
)
from app.pipelines import service

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=config.REDIS_URL,
    enabled=config.ENABLE_RATE_LIMITING,
)


# ── Step definition registry ────────────────────────────────────────────


@router.get("/step-types", response_model=list[str])
async def list_step_types():
    """Return the set of registered step types."""
    return step_types()


# ── Pipeline CRUD ────────────────────────────────────────────────────────


@router.post("/", response_model=PipelineInDB, status_code=status.HTTP_201_CREATED)
@limiter.limit(f"{config.RATE_LIMIT_REGISTER}/minute")
async def create(
    request: Request,
    payload: PipelineCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new pipeline owned by the authenticated user."""
    return await create_pipeline(db, payload, current_user.id)


@router.get("/", response_model=list[PipelineInDB])
async def list_pipelines_endpoint(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List pipelines belonging to the authenticated user."""
    return await list_pipelines(db, current_user.id)


@router.get("/{pipeline_id}", response_model=PipelineInDB)
async def retrieve(
    pipeline_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a single pipeline by ID (user-scoped)."""
    result = await get_pipeline(db, pipeline_id, current_user.id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline not found",
        )
    return result


# ── Run a pipeline ──────────────────────────────────────────────────────


@router.post(
    "/{pipeline_id}/run",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(f"{config.RATE_LIMIT_LOGIN}/minute")
async def run(
    request: Request,
    pipeline_id: int,
    payload: TaskCreate | None = None,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Trigger a pipeline run.

    If ``payload.version_id`` is omitted the latest version is used.
    """
    if payload is None:
        payload = TaskCreate(pipeline_id=pipeline_id)
    else:
        payload = TaskCreate(
            pipeline_id=pipeline_id,
            version_id=payload.version_id,
            trigger_type=payload.trigger_type or "manual",
        )
    return await trigger_run(db, payload, current_user.id)


# ── Pipeline version ────────────────────────────────────────────────────


@router.get(
    "/{pipeline_id}/versions",
    response_model=list[PipelineVersionInDB],
)
async def list_versions(
    pipeline_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List versions of a given pipeline."""
    # Verify pipeline ownership first
    from app.pipelines.service import get_pipeline

    pipeline = await get_pipeline(db, pipeline_id, current_user.id)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline not found",
        )
    from app.pipelines.service import list_versions as _list_versions

    return await _list_versions(db, pipeline_id, current_user.id)


@router.post(
    "/{pipeline_id}/versions",
    response_model=PipelineVersionInDB,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    pipeline_id: int,
    payload: PipelineVersionBase,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new immutable pipeline version."""
    return await service.create_version(db, pipeline_id, payload, current_user.id)
