"""transform step: map inputs into outputs via templates.

Config shape (decision 3):

    {"mapping": {"price": "{{items.0.price}}", "name": "item {{items.0.name}}"}}

Each template is resolved with the resolver, which preserves JSON type for a
lone ``{{path}}`` and interpolates into a string otherwise. The resolved
values are written to ``ctx.outputs``. Templates may reference prior outputs
within the same step by name, so the mapping is applied in order.
"""

from __future__ import annotations

from typing import Any

from app.steps.base import Step, StepContext, StepOutcome, StepResult
from app.steps.resolver import resolve


class TransformStep(Step):
    step_type = "transform"

    def __init__(self, config: dict[str, Any]) -> None:
        mapping = config.get("mapping")
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("config.mapping must be a non-empty object")
        for key in mapping:
            if not isinstance(key, str) or not key:
                raise ValueError("config.mapping keys must be non-empty strings")
        self.mapping: dict[str, Any] = mapping

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        mapping = config.get("mapping")
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("config.mapping must be a non-empty object")
        for key in mapping:
            if not isinstance(key, str) or not key:
                raise ValueError("config.mapping keys must be non-empty strings")

    async def execute(self, ctx: StepContext) -> StepResult:
        # Build a context that includes inputs, prior outputs, and variables.
        # Prior outputs are flattened so templates can reference them by name.
        context: dict[str, Any] = {
            "inputs": ctx.inputs,
            **ctx.outputs,
            **ctx.variables,
        }
        for key, template in self.mapping.items():
            try:
                ctx.outputs[key] = resolve(template, context)
            except KeyError as e:
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"template error: unresolved variable {e} in mapping {key!r}",
                )
            # Make this output available to later keys in the same mapping.
            context[key] = ctx.outputs[key]
        return StepResult(outcome=StepOutcome.SUCCEEDED, output=dict(ctx.outputs))