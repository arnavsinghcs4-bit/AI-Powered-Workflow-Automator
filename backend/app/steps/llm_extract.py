"""llm_extract step: extract structured data from text using LLM provider with credentials."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.steps.base import Step, StepContext, StepOutcome, StepResult
from app.steps.resolver import resolve
from app.providers.anthropic_provider import AnthropicProvider


class LLMExtractStep(Step):
    step_type = "llm_extract"

    def __init__(
        self,
        config: dict[str, Any],
        llm_provider: Optional[AnthropicProvider] = None,
        credential_resolver=None,
        token_budget: Optional[int] = None,
        user_id: Optional[int] = None,
        step_run_id: Optional[int] = None,
    ) -> None:
        # Template for the prompt
        prompt = config.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("config.prompt is required and must be a string")
        self.prompt_template = prompt

        # JSON schema for output validation
        json_schema = config.get("json_schema")
        if not isinstance(json_schema, dict) or not json_schema:
            raise ValueError("config.json_schema is required and must be an object")
        self.json_schema = json_schema

        # Optional model override (defaults to credential's model)
        model = config.get("model")
        if model is not None and not isinstance(model, str):
            raise ValueError("config.model must be a string")
        self.model = model

        # Optional temperature (default 0.0)
        temperature = config.get("temperature", 0.0)
        if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 2:
            raise ValueError("config.temperature must be a number between 0 and 2")
        self.temperature = float(temperature)

        # Optional max_tokens (default from model)
        max_tokens = config.get("max_tokens", 4096)
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError("config.max_tokens must be a positive integer")
        self.max_tokens = int(max_tokens)

        # Credential reference (required, must be api_key kind for Anthropic)
        credential_name = config.get("credential")
        if not isinstance(credential_name, str) or not credential_name:
            raise ValueError("config.credential is required and must be a string")
        self.credential_name = credential_name

        self.llm_provider = llm_provider
        self.credential_resolver = credential_resolver
        self.token_budget = token_budget
        self.user_id = user_id
        self.step_run_id = step_run_id

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        prompt = config.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("config.prompt is required and must be a string")
        json_schema = config.get("json_schema")
        if not isinstance(json_schema, dict) or not json_schema:
            raise ValueError("config.json_schema is required and must be an object")
        model = config.get("model")
        if model is not None and not isinstance(model, str):
            raise ValueError("config.model must be a string")
        temperature = config.get("temperature", 0.0)
        if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 2:
            raise ValueError("config.temperature must be a number between 0 and 2")
        max_tokens = config.get("max_tokens", 4096)
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError("config.max_tokens must be a positive integer")
        credential = config.get("credential")
        if not isinstance(credential, str) or not credential:
            raise ValueError("config.credential is required and must be a string")

    async def execute(self, ctx: StepContext) -> StepResult:
        # Resolve prompt template
        try:
            prompt = resolve(self.prompt_template, ctx.variables)
        except KeyError as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"template error: unresolved variable {e}",
            )

        if not isinstance(prompt, str):
            return StepResult(
                outcome=StepOutcome.FAILED,
                error="config.prompt must resolve to a string",
            )

        # Resolve model if template
        model = self.model
        if model is not None:
            try:
                model = resolve(model, ctx.variables)
            except KeyError as e:
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"template error: unresolved variable {e}",
                )

        # Resolve credential
        if not self.credential_resolver:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error="credential resolver not available",
            )

        try:
            cred_payload = await self.credential_resolver(self.credential_name)
            kind = cred_payload.get("kind") if isinstance(cred_payload, dict) else None
            if kind != "api_key":
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"credential '{self.credential_name}' must be of kind 'api_key'",
                )
        except Exception as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"credential resolution failed: {e}",
            )

        # Build LLM provider from credential
        api_key = cred_payload.get("api_key") or cred_payload.get("token")
        if not api_key:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error="credential missing api_key or token field",
            )

        # Use model from credential if not overridden
        final_model = model or cred_payload.get("model") or "claude-3-haiku-20240307"

        provider = AnthropicProvider(api_key=api_key)

        # Execute LLM call with token budget tracking
        start_time = time.monotonic()
        input_tokens = 0
        output_tokens = 0
        status = "succeeded"
        error = None
        output = None

        try:
            # Check token budget if available
            if self.token_budget is not None and self.user_id is not None:
                from app.credentials.service import get_llm_token_usage
                used = await get_llm_token_usage(self.user_id)
                estimated_input = len(prompt) // 4  # rough estimate
                if used + estimated_input + self.max_tokens > self.token_budget:
                    return StepResult(
                        outcome=StepOutcome.FAILED,
                        error=f"Token budget exceeded: used {used}, budget {self.token_budget}",
                    )

            result = await provider.complete(
                model=final_model,
                prompt=prompt,
                json_schema=self.json_schema,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            output = result.output
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens

        except RuntimeError as e:
            error_msg = str(e)
            if error_msg.startswith("RATE_LIMIT:"):
                status = "rate_limited"
                error = "Rate limit exceeded"
            else:
                status = "failed"
                error = error_msg
        except Exception as e:
            status = "failed"
            error = f"{type(e).__name__}: {e}"
        finally:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            await provider.close()

            # Record LLM call if we have the context
            if self.step_run_id is not None and self.user_id is not None:
                try:
                    from app.credentials.service import record_llm_call
                    await record_llm_call(
                        step_run_id=self.step_run_id,
                        user_id=self.user_id,
                        provider="anthropic",
                        model=final_model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_ms=latency_ms,
                        status=status,
                    )
                except Exception:
                    # Don't fail the step if recording fails
                    pass

        if error:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=error,
                output={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                    "status": status,
                },
            )

        return StepResult(
            outcome=StepOutcome.SUCCEEDED,
            output={
                "extracted": output,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "model": final_model,
            },
        )