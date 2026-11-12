"""Structured logger for run execution events.

Emits JSON-log lines keyed by ``run_id`` and ``step_run_id`` for correlation
with tracing systems. Every step execution writes one structured log entry.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

from app.execution.serializers import redact


class RunLogger:
    """Central logger for a single pipeline run."""

    def __init__(self, run_id: int, step_run_id: int | None = None) -> None:
        self.run_id = run_id
        self.step_run_id = step_run_id
        self._log = sys.stdout  # in production: structured sink / Loki / Datadog

    def _emit(self, event: dict[str, Any]) -> None:
        # Redact anything that might contain secrets before persisting.
        safe = redact(event)
        line = json.dumps(safe, sort_keys=True)
        self._log.write(line + "\n")
        self._log.flush()

    def step_started(self, step_run_id: int, step_type: str) -> None:
        self._emit(
            {
                "event": "step_started",
                "run_id": self.run_id,
                "step_run_id": step_run_id,
                "step_type": step_type,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )

    def step_finished(
        self,
        step_run_id: int,
        step_type: str,
        outcome: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._emit(
            {
                "event": "step_finished",
                "run_id": self.run_id,
                "step_run_id": step_run_id,
                "step_type": step_type,
                "outcome": outcome,
                "output": output or {},
                "error": error or "",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )

    def run_finished(self, outcome: str, error: str | None = None) -> None:
        self._emit(
            {
                "event": "run_finished",
                "run_id": self.run_id,
                "outcome": outcome,
                "error": error or "",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )


# Module-level helper so routes can do ``logger = RunLogger(run_id)`` and
# then call ``logger.step_started(...)`` etc.
logger: RunLogger | None = None


def set_logger(run_id: int, step_run_id: int | None = None) -> None:
    global logger
    logger = RunLogger(run_id, step_run_id)
