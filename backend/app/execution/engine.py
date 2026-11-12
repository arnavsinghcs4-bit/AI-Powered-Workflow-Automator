"""Scheduler: submit a pipeline run to the Celery worker.

The worker lives in ``app/worker/tasks.py`` and expects ``run_id`` and a
list of step instances. This module bridges the gap: it serialises the
step definitions and dispatches the task.
"""

from __future__ import annotations

from typing import Any


async def submit_run(
    run_id: int,
    steps_data: dict[str, Any],
    definition: dict[str, Any],
) -> None:
    """Submit a pipeline run to the Celery worker.

    Args:
        run_id: the DB row id of the new run.
        steps_data: serialised step definitions keyed by node_id.
        definition: the full pipeline version definition dict.
    """
    # Set up per-run logger so we get structured output per run_id.
    from app.execution.logging import set_logger

    set_logger(run_id)

    # Fire-and-forget: the Celery task does the actual orchestration.
    from app.worker.celery_app import celery_app

    celery_app.send_task(
        "scheduler.submit_run",
        args=[run_id, steps_data, definition],
    )
