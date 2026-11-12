"""Tests for app.steps.http_request and app.steps.transform."""

import asyncio
import pytest

from app.steps.base import StepContext, StepOutcome
from app.steps.http_request import HttpRequestStep
from app.steps.transform import TransformStep


def _mk_ctx(inputs=None, variables=None, outputs=None):
    return StepContext(
        run_id=1,
        step_run_id=1,
        attempt=1,
        inputs=inputs or {},
        variables=variables or {},
        outputs=outputs or {},
    )


def test_transform_lone_template_preserves_int():
    step = TransformStep({"mapping": {"x": "{{a}}"}})
    ctx = _mk_ctx(variables={"a": 42})
    result = asyncio.run(step.execute(ctx))
    assert result.outcome == StepOutcome.SUCCEEDED
    assert result.output["x"] == 42


def test_transform_lone_template_preserves_bool():
    step = TransformStep({"mapping": {"f": "{{a}}"}})
    ctx = _mk_ctx(variables={"a": False})
    result = asyncio.run(step.execute(ctx))
    assert result.output["f"] is False


def test_transform_lone_template_preserves_dict():
    step = TransformStep({"mapping": {"o": "{{a}}"}})
    ctx = _mk_ctx(variables={"a": {"b": 1}})
    result = asyncio.run(step.execute(ctx))
    assert result.output["o"] == {"b": 1}


def test_transform_interpolation_coerces_to_string():
    step = TransformStep({"mapping": {"s": "val {{a}}"}})
    ctx = _mk_ctx(variables={"a": 7})
    result = asyncio.run(step.execute(ctx))
    assert result.output["s"] == "val 7"


def test_transform_chained_outputs():
    # First output "a" feeds second template
    step = TransformStep({"mapping": {"a": "{{x}}", "b": "prefix_{{a}}"}})
    ctx = _mk_ctx(variables={"x": 9})
    result = asyncio.run(step.execute(ctx))
    assert result.output["a"] == 9
    assert result.output["b"] == "prefix_9"


def test_transform_missing_variable_fails():
    step = TransformStep({"mapping": {"x": "{{missing}}"}})
    ctx = _mk_ctx(variables={})
    result = asyncio.run(step.execute(ctx))
    assert result.outcome == StepOutcome.FAILED
    assert "unresolved variable" in result.error


def test_http_request_validates_config():
    with pytest.raises(ValueError, match="required"):
        HttpRequestStep({"url": ""})  # empty url
    with pytest.raises(ValueError, match="unsupported method"):
        HttpRequestStep({"url": "http://x", "method": "INVALID"})
    with pytest.raises(ValueError, match="must be an object"):
        HttpRequestStep({"url": "http://x", "headers": "not-a-dict"})
    with pytest.raises(ValueError, match="positive number"):
        HttpRequestStep({"url": "http://x", "timeout": -1})
    with pytest.raises(ValueError, match="non-negative integer"):
        HttpRequestStep({"url": "http://x", "retries": -1})


def test_http_request_mock_client_success():
    """Test a successful http_request step using a mock client."""

    async def mock_client_factory():
        class MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, method, url, headers, json):
                assert method == "POST"
                assert url == "http://example.com/api"
                assert headers == {"content-type": "application/json"}
                assert json == {"key": "value"}
                return MockResponse()

        class MockResponse:
            status_code = 200
            headers = {"content-type": "application/json"}
            text = '{"ok": true}'

        return MockClient()

    step = HttpRequestStep(
        {
            "method": "POST",
            "url": "http://example.com/api",
            "headers": {"content-type": "application/json"},
            "body": {"key": "value"},
        },
        client_factory=mock_client_factory,
    )
    ctx = _mk_ctx()
    result = asyncio.run(step.execute(ctx))
    assert result.outcome == StepOutcome.SUCCEEDED
    assert result.output["status"] == 200
    assert result.output["body"] == '{"ok": true}'
    assert "duration_ms" in result.output


def test_http_request_mock_client_404_no_retry():
    """404 is not in retryable status -> succeed with response (no retry)."""

    async def mock_client_factory():
        class MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, method, url, headers=None, json=None):
                return MockResponse()

        class MockResponse:
            status_code = 404
            headers = {}
            text = "not found"

        return MockClient()

    step = HttpRequestStep(
        {"url": "http://example.com/404", "retries": 2},
        client_factory=mock_client_factory,
    )
    ctx = _mk_ctx()
    result = asyncio.run(step.execute(ctx))
    # 404 is not retryable, but it's still a valid HTTP response
    assert result.outcome == StepOutcome.SUCCEEDED
    assert result.output["status"] == 404


def test_http_request_mock_client_500_retries_then_fails():
    """500 is retryable, should retry retries times then fail."""

    calls = {"count": 0}

    async def mock_client_factory():
        class MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, method, url, headers=None, json=None):
                calls["count"] += 1
                return MockResponse()

        class MockResponse:
            status_code = 500
            headers = {}
            text = "server error"

        return MockClient()

    step = HttpRequestStep(
        {"url": "http://example.com/500", "retries": 2},
        client_factory=mock_client_factory,
    )
    ctx = _mk_ctx()
    result = asyncio.run(step.execute(ctx))
    assert result.outcome == StepOutcome.FAILED
    assert calls["count"] == 3  # initial + 2 retries


def test_http_request_template_in_url():
    """URL template resolved from variables."""

    async def mock_client_factory():
        class MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, method, url, headers=None, json=None):
                assert url == "http://api.example.com/v1/users/42"
                return MockResponse()

        class MockResponse:
            status_code = 200
            headers = {}
            text = "ok"

        return MockClient()

    step = HttpRequestStep(
        {"url": "http://api.example.com/v1/users/{{user_id}}"},
        client_factory=mock_client_factory,
    )
    ctx = _mk_ctx(variables={"user_id": 42})
    result = asyncio.run(step.execute(ctx))
    assert result.outcome == StepOutcome.SUCCEEDED


def test_http_request_ssrf_error_fails_fast():
    """SSRF error is not retried."""

    async def mock_client_factory():
        class MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, method, url, headers=None, json=None):
                from app.steps.ssrf import SsrfError
                raise SsrfError("blocked IP")

        return MockClient()

    step = HttpRequestStep(
        {"url": "http://10.0.0.1/", "retries": 2},
        client_factory=mock_client_factory,
    )
    ctx = _mk_ctx()
    result = asyncio.run(step.execute(ctx))
    assert result.outcome == StepOutcome.FAILED
    assert "blocked" in result.error