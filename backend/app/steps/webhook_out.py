"""webhook_out step: POST/PUT JSON to a URL with optional auth via credential.
Reuses the SSRF-pinned HTTP client from http_request.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from app.steps.base import Step, StepContext, StepOutcome, StepResult
from app.steps.resolver import resolve
from app.providers.http_client import SharedHTTPClient
from app.steps.ssrf import SsrfError


ALLOWED_METHODS = {"POST", "PUT", "PATCH"}
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class WebhookOutStep(Step):
    step_type = "webhook_out"

    def __init__(
        self,
        config: dict[str, Any],
        http_client: Optional[SharedHTTPClient] = None,
        credential_resolver=None,
    ) -> None:
        method = str(config.get("method", "POST")).upper()
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

        body = config.get("body")
        if body is not None and not isinstance(body, (dict, list)):
            raise ValueError("config.body must be a JSON object or array")
        self.body = body

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

        # Optional credential reference for authentication
        credential_name = config.get("credential")
        if credential_name is not None and not isinstance(credential_name, str):
            raise ValueError("config.credential must be a string")
        self.credential_name = credential_name

        self.http_client = http_client
        self.credential_resolver = credential_resolver

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        method = config.get("method", "POST")
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
        body = config.get("body")
        if body is not None and not isinstance(body, (dict, list)):
            raise ValueError("config.body must be a JSON object or array")
        timeout = config.get("timeout", 10)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("config.timeout must be a positive number")
        retries = config.get("retries", 2)
        if not isinstance(retries, int) or retries < 0:
            raise ValueError("config.retries must be a non-negative integer")
        credential = config.get("credential")
        if credential is not None and not isinstance(credential, str):
            raise ValueError("config.credential must be a string")

    async def execute(self, ctx: StepContext) -> StepResult:
        import time

        # Resolve URL
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

        # Resolve headers
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

        # Resolve body
        body = None
        if self.body is not None:
            body = resolve(self.body, ctx.variables)

        # Resolve credential for auth if specified
        if self.credential_name and self.credential_resolver:
            try:
                cred_payload = await self.credential_resolver(self.credential_name)
                # Apply credential based on kind
                kind = cred_payload.get("kind") if isinstance(cred_payload, dict) else None
                if kind == "api_key":
                    # Assume API key goes in Authorization header as Bearer
                    api_key = cred_payload.get("api_key") or cred_payload.get("token")
                    if api_key:
                        headers["Authorization"] = f"Bearer {api_key}"
                elif kind == "bearer":
                    token = cred_payload.get("token")
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                elif kind == "basic":
                    username = cred_payload.get("username")
                    password = cred_payload.get("password")
                    if username and password:
                        import base64
                        auth = base64.b64encode(f"{username}:{password}".encode()).decode()
                        headers["Authorization"] = f"Basic {auth}"
            except Exception as e:
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"credential resolution failed: {e}",
                )

        # Get or create HTTP client
        client = self.http_client or SharedHTTPClient(default_timeout=self.timeout)

        attempts = self.retries + 1
        last_error: Optional[str] = None

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = await client.request(
                    self.method,
                    url,
                    headers=headers,
                    content=json.dumps(body).encode() if body is not None else None,
                    timeout=self.timeout,
                )
            except SsrfError as e:
                return StepResult(outcome=StepOutcome.FAILED, error=str(e))
            except Exception as e:
                # Network error, timeout, etc. - retryable
                if attempt < attempts - 1:
                    last_error = f"{type(e).__name__}: {e}"
                    continue
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
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error=f"status {response.status_code} after {attempts} attempts",
                )

            # Non-retryable status -> succeed with response
            try:
                response_body = response.body.decode("utf-8")
            except UnicodeDecodeError:
                response_body = response.body.hex()

            return StepResult(
                outcome=StepOutcome.SUCCEEDED,
                output={
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": response_body,
                    "duration_ms": duration_ms,
                },
            )

        return StepResult(
            outcome=StepOutcome.FAILED,
            error=last_error or "request failed",
        )