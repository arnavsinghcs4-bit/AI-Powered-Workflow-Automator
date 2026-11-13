"""Service layer for pipeline CRUD and run orchestration."""

from __future__ import annotations


from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.steps.registry import (
    build_steps,
    validate_definition,
    StepValidationError,
)
from app.pipelines.models import Pipeline, PipelineVersion, Run, StepRun
from app.pipelines.schemas import (
    PipelineCreate,
    PipelineInDB,
    PipelineVersionBase,
    PipelineVersionInDB,
    TaskCreate,
    TaskResponse,
)
from app.execution.engine import submit_run


async def _next_version_number(db: AsyncSession, pipeline_id: int) -> int:
    """Return the next version number for this pipeline."""
    result = await db.execute(
        select(PipelineVersion.version_number)
        .where(PipelineVersion.pipeline_id == pipeline_id)
        .order_by(PipelineVersion.version_number.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    return (last or 0) + 1


async def create_pipeline(
    db: AsyncSession,
    payload: PipelineCreate,
    user_id: int,
) -> PipelineInDB:
    """Create a new pipeline owned by *user_id*."""
    pipeline = Pipeline(
        user_id=user_id,
        name=payload.name,
        description=payload.description,
    )
    db.add(pipeline)
    await db.commit()
    await db.refresh(pipeline)
    return PipelineInDB(
        id=pipeline.id,
        user_id=pipeline.user_id,
        name=pipeline.name,
        description=pipeline.description,
        is_active=pipeline.is_active,
        current_version_id=pipeline.current_version_id,
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
    )


async def get_pipeline(
    db: AsyncSession,
    pipeline_id: int,
    user_id: int,
) -> PipelineInDB | None:
    """Return the pipeline row if it belongs to *user_id*, else None."""
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return PipelineInDB(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        description=row.description,
        is_active=row.is_active,
        current_version_id=row.current_version_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_pipelines(
    db: AsyncSession,
    user_id: int,
) -> list[PipelineInDB]:
    """Return all pipelines owned by *user_id*."""
    result = await db.execute(select(Pipeline).where(Pipeline.user_id == user_id))
    rows = result.scalars().all()
    return [
        PipelineInDB(
            id=r.id,
            user_id=r.user_id,
            name=r.name,
            description=r.description,
            is_active=r.is_active,
            current_version_id=r.current_version_id,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


async def list_versions(
    db: AsyncSession,
    pipeline_id: int,
    user_id: int,
) -> list[PipelineVersionInDB]:
    """Return versions for this pipeline (user-scoped)."""
    result = await db.execute(
        select(PipelineVersion)
        .where(PipelineVersion.pipeline_id == pipeline_id)
        .order_by(PipelineVersion.version_number.desc())
    )
    rows = result.scalars().all()
    return [
        PipelineVersionInDB(
            id=r.id,
            pipeline_id=r.pipeline_id,
            version_number=r.version_number,
            definition=r.definition,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def create_version(
    db: AsyncSession,
    pipeline_id: int,
    payload: PipelineVersionBase,
    user_id: int,
) -> PipelineVersionInDB:
    """Create a new pipeline version."""
    # Verify pipeline ownership
    pipeline_result = await get_pipeline(db, pipeline_id, user_id)
    if pipeline_result is None:
        raise HTTPException(
            status_code=404,
            detail="Pipeline not found",
        )

    # Use user-provided version_number (validated by schema)
    version_number = payload.version_number

    # Check for duplicate version_number
    existing = await db.execute(
        select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline_id,
            PipelineVersion.version_number == version_number,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Version {version_number} already exists for this pipeline",
        )

    version = PipelineVersion(
        pipeline_id=pipeline_id,
        version_number=version_number,
        definition=payload.definition,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)

    return PipelineVersionInDB(
        id=version.id,
        pipeline_id=version.pipeline_id,
        version_number=version.version_number,
        definition=version.definition,
        created_at=version.created_at,
    )


async def trigger_run(
    db: AsyncSession,
    payload: TaskCreate,
    user_id: int,
) -> TaskResponse:
    """Create a run and submit it to the Celery worker."""

    # Resolve the version_id.
    version_id = payload.version_id
    if version_id is None:
        # Grab latest version.
        versions = await list_versions(db, payload.pipeline_id, user_id)
        if not versions:
            raise HTTPException(
                status_code=404,
                detail="No pipeline versions exist",
            )
        version_id = versions[0].id  # highest version_number

    # Load the pipeline and its current version.
    pipeline_result = await get_pipeline(db, payload.pipeline_id, user_id)
    if pipeline_result is None:
        raise HTTPException(
            status_code=404,
            detail="Pipeline not found",
        )

    version_result = await db.execute(
        select(PipelineVersion).where(PipelineVersion.id == version_id)
    )
    version = version_result.scalar_one()

    # Validate the definition before creating a run.
    try:
        validate_definition(version.definition.get("nodes", []))
    except StepValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid pipeline definition: {e}",
        )

    # Build step instances for the worker and serialize definitions.
    steps = build_steps(version.definition.get("nodes", []))
    steps_data = {node_id: node["config"] for node_id, node in zip(steps.keys(), version.definition.get("nodes", []))}

    # Persist a run row.
    run = Run(
        pipeline_id=pipeline_result.id,
        version_id=version_id,
        user_id=user_id,
        status="pending",
        trigger_type=payload.trigger_type,
    )
    db.add(run)
    await db.flush()

    # Persist a step_run row for each step.
    for node_id, step in steps.items():
        sr = StepRun(
            run_id=run.id,
            node_id=node_id,
            step_type=step.step_type,
            status="pending",
            attempt=1,
        )
        db.add(sr)

    await db.commit()
    await db.refresh(run)

    # Submit to the worker via the scheduler.
    try:
        await submit_run(run.id, steps_data, version.definition)
    except Exception as e:
        # If the scheduler fails, roll back the run and re-raise.
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit run: {e}",
        )

    return TaskResponse(
        run_id=run.id,
        pipeline_id=pipeline_result.id,
        version_id=version_id,
        status=run.status,
        message="Pipeline run submitted",
    )
