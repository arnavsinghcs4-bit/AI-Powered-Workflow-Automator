"""http_request step: an outbound HTTP call with SSRF protection and retries.

Retry policy (decision 8): retry only on network errors, timeouts, 5xx,
408 and 429. Fail fast on config errors, SSRF, template errors and other
4xx. Output is the raw response: status, headers, body, duration_ms.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.steps.base import Step, StepContext, StepOutcome, StepResult
from app.steps.resolver import resolve
from app.steps.ssrf import SsrfError, build_client

ALLOWED_METHODS = {
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "HEAD",
    "OPTIONS",
}
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class HttpRequestStep(Step):
    step_type = "http_request"

    def __init__(
        self,
        config: dict[str, Any],
        client_factory=None,
    ) -> None:
        # Validate config first (shared with validate_config classmethod)
        method = str(config.get("method", "GET")).upper()
        if method not in ALLOWED_METHODS:
            raise ValueError(
                f"unsupported method {method!r}; allowed: {sorted(ALLOWED_METHODS)}"
            )
        self.method = method
        url = config.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("config.url is required and must be a string")
        self.url_template = url
        headers = config.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("config.headers must be an object")
        self.headers = headers or {}
        self.body = config.get("body")
        timeout = config.get("timeout", 10)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("config.timeout must be a positive number")
        self.timeout = float(timeout)
        retries = config.get("retries", 2)
        if not isinstance(retries, int) or retries < 0:
            raise ValueError("config.retries must be a non-negative integer")
        self.retries = int(retries)
        retry_on = config.get("retry_on_status")
        if retry_on is None:
            self.retry_on_status = set(RETRYABLE_STATUS)
        else:
            self.retry_on_status = set(int(s) for s in retry_on)
        # client_factory lets tests inject a mock transport; production uses
        # the SSRF-protected builder.
        self.client_factory = client_factory or (lambda: build_client(timeout=self.timeout))

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        method = config.get("method", "GET")
        if not isinstance(method, str) or method.upper() not in ALLOWED_METHODS:
            raise ValueError(
                f"unsupported method {method!r}; allowed: {sorted(ALLOWED_METHODS)}"
            )
        url = config.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("config.url is required and must be a string")
        headers = config.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("config.headers must be an object")
        timeout = config.get("timeout", 10)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("config.timeout must be a positive number")
        retries = config.get("retries", 2)
        if not isinstance(retries, int) or retries < 0:
            raise ValueError("config.retries must be a non-negative integer")

    async def execute(self, ctx: StepContext) -> StepResult:
        import asyncio
        import time
        try:
            url = resolve(self.url_template, ctx.variables)
        except KeyError as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"template error: unresolved variable {e}",
            )
        if not isinstance(url, str):
            return StepResult(
                outcome=StepOutcome.FAILED,
                error="config.url must resolve to a string",
            )

        try:
            headers = {
                k: resolve(v, ctx.variables) for k, v in self.headers.items()
            }
        except KeyError as e:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error=f"template error: unresolved variable {e}",
            )
        headers = {k: str(v) for k, v in headers.items()}

        body = resolve(self.body, ctx.variables) if self.body is not None else None

        attempts = self.retries + 1
        last_error: str | None = None
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                client = self.client_factory()
                if asyncio.iscoroutine(client):
                    client = await client
                async with client as c:
                    response = await c.request(
                        self.method, url, headers=headers, json=body
                    )
            except SsrfError as e:
                return StepResult(outcome=StepOutcome.FAILED, error=str(e))
            except httpx.HTTPError as e:
                # Any httpx failure that isn't a retryable network condition
                # is a config/transport bug, not a retryable condition -- fail fast.
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"{type(e).__name__}: {e}",
                )

            duration_ms = int((time.monotonic() - started) * 1000)
            if response.status_code in self.retry_on_status:
                if attempt < attempts - 1:
                    last_error = (
                        f"retryable status {response.status_code} on attempt {attempt + 1}"
                    )
                    continue
                # Retryable status but no retries left -> fail
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"status {response.status_code} after {attempts} attempts",
                )

            # Non-retryable status -> succeed with response
            return StepResult(
                outcome=StepOutcome.SUCCEEDED,
                output={
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text,
                    "duration_ms": duration_ms,
                },
            )

        return StepResult(
            outcome=StepOutcome.FAILED,
            error=last_error or "request failed",
        )