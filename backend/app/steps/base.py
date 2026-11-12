"""Base types for pipeline step execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class StepContext:
    """Everything a step needs to run, and nothing more."""

    run_id: int
    step_run_id: int
    attempt: int
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    outcome: StepOutcome
    output: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class Step:
    """A single pipeline node. Subclasses set ``step_type``."""

    step_type: str = "step"

    async def execute(self, ctx: StepContext) -> StepResult:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"step_type": self.step_type}
