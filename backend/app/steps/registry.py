"""Step registry: validates step config at save time and builds steps at run time.

A pipeline definition is a list of nodes::

    [{"id": "step1", "type": "http_request", "config": {...}},
     {"id": "step2", "type": "transform", "config": {"mapping": {...}}}]

The registry owns validation: an invalid definition is rejected by the API
before it is persisted as a PipelineVersion, and again by the worker before
execution. Validation here is pure and unit-testable.
"""

from __future__ import annotations

from typing import Any

from app.steps.base import Step
from app.steps.http_request import HttpRequestStep
from app.steps.transform import TransformStep

STEP_TYPES = {
    "http_request": HttpRequestStep,
    "transform": TransformStep,
}


class StepValidationError(Exception):
    """Raised when a step config is invalid."""


def validate_definition(definition: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate a pipeline definition; return it unchanged on success."""
    if not isinstance(definition, list):
        raise StepValidationError("definition must be a list of nodes")
    if not definition:
        raise StepValidationError("definition must contain at least one node")

    seen_ids: set[str] = set()
    for node in definition:
        if not isinstance(node, dict):
            raise StepValidationError("each node must be an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise StepValidationError("node.id must be a non-empty string")
        if node_id in seen_ids:
            raise StepValidationError(f"duplicate node id: {node_id!r}")
        seen_ids.add(node_id)

        node_type = node.get("type")
        if node_type not in STEP_TYPES:
            raise StepValidationError(
                f"unknown step type {node_type!r}; allowed: {sorted(STEP_TYPES)}"
            )
        config = node.get("config")
        if not isinstance(config, dict):
            raise StepValidationError(f"node {node_id!r}: config must be an object")
        STEP_TYPES[node_type].validate_config(config)

    return definition


def build_steps(definition: list[dict[str, Any]]) -> dict[str, Step]:
    """Build a {node_id: Step} map from a validated definition."""
    validate_definition(definition)
    steps: dict[str, Step] = {}
    for node in definition:
        steps[node["id"]] = STEP_TYPES[node["type"]](node["config"])
    return steps


def step_types() -> list[str]:
    return sorted(STEP_TYPES)
