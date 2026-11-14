"""Celery worker tasks for pipeline execution.

Phase 3: execute a pipeline run step-by-step inside the worker's sync
loop. Each step runs in its own ``asyncio.run`` with a fresh engine +
session (NullPool), per decision 11 of the spec.

The worker connects via the sync engine (``get_sync_engine``,
``prepare_threshold=None``) and runs outside RLS (no ``app.user`` GUC set).
Owner scoping is enforced by the API layer; the worker's blast radius is
bounded by SSRF + secret redaction + input validation (see the spec's
Security section).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from celery import shared_task
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.execution.logging import set_logger
from app.pipelines.models import Run, StepRun
from app.worker.database import sync_engine

# Sync session factory for the worker's sync loop.
_sync_session_maker = sessionmaker(bind=sync_engine, expire_on_commit=False)


def _atomic_claim(run_id: int) -> int | None:
    """Atomically claim a pending run by flipping status -> running.

    Returns the run id on success, None if the run is not pending.
    Decision 7: the claim is a single UPDATE with a WHERE on status, so
    two workers can never both claim the same run.
    """
    with _sync_session_maker() as session:
        result = session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == "pending")
            .values(
                status="running",
                claimed_at=datetime.now(timezone.utc),
            )
            .returning(Run.id)
        )
        claimed = result.scalar_one_or_none()
        session.commit()
        return claimed


def _reset_stale_runs() -> None:
    """Re-claim runs that have been running longer than the lease window."""
    from sqlalchemy import text

    with _sync_session_maker() as session:
        session.execute(
            text(
                "UPDATE runs SET status='pending', claimed_at=NULL "
                "WHERE status='running' "
                "AND claimed_at < (now() - interval '5 minutes') "
                "RETURNING id"
            )
        )
        session.commit()


def _load_steps(run_id: int) -> list[dict[str, Any]]:
    """Load the step_runs for a run, ordered by node_id."""
    with _sync_session_maker() as session:
        result = session.execute(
            select(StepRun).where(StepRun.run_id == run_id).order_by(StepRun.node_id)
        )
        return [
            {
                "id": sr.id,
                "node_id": sr.node_id,
                "step_type": sr.step_type,
                "attempt": sr.attempt,
                "input": sr.input or {},
            }
            for sr in result.scalars().all()
        ]


def _mark_step(
    step_run_id: int,
    status: str,
    output: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with _sync_session_maker() as session:
        session.execute(
            update(StepRun)
            .where(StepRun.id == step_run_id)
            .values(
                status=status,
                output=output,
                error=error,
                finished_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def _mark_run(run_id: int, status: str, error: str | None = None) -> None:
    with _sync_session_maker() as session:
        session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(status=status, error=error, finished_at=datetime.now(timezone.utc))
        )
        session.commit()


@shared_task(bind=True, name="scheduler.submit_run")
def submit_run(
    self, run_id: int, steps_data: dict[str, Any], definition: dict[str, Any]
) -> None:
    """Execute a pipeline run step-by-step.

    ``steps_data`` is a dict of {node_id: step_config} and ``definition``
    is the full pipeline version definition. The worker resolves the
    step type from ``steps_data`` and runs each one in its own
    ``asyncio.run``.
    """
    set_logger(run_id)

    # Re-claim stale runs before starting.
    _reset_stale_runs()

    # Atomically claim the run.
    if _atomic_claim(run_id) is None:
        # Already claimed by another worker, or not pending.
        return

    # Load the step_runs for this run.
    steps = _load_steps(run_id)
    if not steps:
        _mark_run(run_id, "failed", error="No step_runs found for run")
        return

    # Build Step instances from the definition.
    from app.steps.registry import build_steps

    try:
        step_instances = build_steps(definition.get("nodes", []))
    except Exception as e:
        _mark_run(run_id, "failed", error=f"Step build failed: {e}")
        return

    node_to_step = {
        node["id"]: step
        for node in definition.get("nodes", [])
        for step in [step_instances.get(node["id"])]
    }
    # Fallback: if node ids don't match, try by step_type.
    if not node_to_step:
        node_to_step = {s["node_id"]: step_instances.get(s["step_type"]) for s in steps}

    failed = False
    for sr in steps:
        step = node_to_step.get(sr["node_id"])
        if step is None:
            _mark_step(sr["id"], "failed", error="Unknown step type")
            failed = True
            break

        from app.steps.base import StepContext

        ctx = StepContext(
            run_id=run_id,
            step_run_id=sr["id"],
            attempt=sr["attempt"],
            inputs=sr["input"],
        )
        try:
            result = asyncio.run(step.execute(ctx))
        except Exception as e:
            _mark_step(sr["id"], "failed", error=f"{type(e).__name__}: {e}")
            failed = True
            break

        if result.outcome.value == "succeeded":
            _mark_step(sr["id"], "succeeded", output=result.output or {})
        else:
            _mark_step(sr["id"], "failed", error=result.error)
            failed = True
            break

    _mark_run(run_id, "failed" if failed else "succeeded")
