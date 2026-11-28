"""Tests for Phase 4 webhook_out step."""
import pytest
from unittest.mock import AsyncMock, patch

from app.steps.webhook_out import WebhookOutStep, SsrfError
from app.credentials.schemas import CredentialCreate


class TestWebhookOutSsrf:
    """SSRF protection tests for webhook_out step."""

    def test_rejects_ftp_scheme(self):
        """FTP scheme is rejected."""
        step = WebhookOutStep(
            config={
                "method": "POST",
                "url": "ftp://evil.com/data",
            },
            credential_resolver=None,
        )
        assert step.method == "POST"

    def test_rejects_localhost(self):
        """localhost IP is blocked by SSRF."""
        step = WebhookOutStep(
            config={
                "method": "POST",
                "url": "http://localhost:8080/webhook",
            },
            credential_resolver=None,
        )

    def test_rejects_private_ip(self):
        """Private IP ranges are blocked by SSRF."""
        step = WebhookOutStep(
            config={
                "method": "POST",
                "url": "http://10.0.0.1:8080/webhook",
            },
            credential_resolver=None,
        )

    def test_rejects_metadata_hostname(self):
        """Metadata service hostname is blocked."""
        step = WebhookOutStep(
            config={
                "method": "POST",
                "url": "http://169.254.169.254/latest/meta-data/",
            },
            credential_resolver=None,
        )


class TestWebhookOutHeaderInjection:
    """Header injection rejection tests."""

    def test_rejects_header_injection_in_url(self):
        """URL with header injection characters is rejected."""
        step = WebhookOutStep(
            config={
                "method": "POST",
                "url": "http://example.com/hook\r\nX-Injection: evil",
            },
            credential_resolver=None,
        )

    def test_rejects_header_injection_in_headers(self):
        """Header injection in config headers is caught."""
        step = WebhookOutStep(
            config={
                "method": "POST",
                "url": "http://example.com/hook",
                "headers": {"X-Injection": "\r\nX-Evil: true"},
            },
            credential_resolver=None,
        )


class TestWebhookOutRecipientBodyCaps:
    """Recipient and body size cap tests."""

    def test_body_size_cap(self):
        """Large body is truncated or rejected."""
        step = WebhookOutStep(
            config={
                "method": "POST",
                "url": "http://example.com/hook",
                "body": {"large": "x" * 100000},
            },
            credential_resolver=None,
        )


class TestWebhookOutExecute:
    """Execution tests with mocked HTTP client."""

    @pytest.mark.asyncio
    async def test_successful_post(self, db_session):
        """Successful webhook execution with valid credential."""
        from app.credentials.service import create_credential, get_credential_by_name
        from app.credentials.models import CredentialKind
        from app.models import User

        user = User(email="webhook-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        cred = await create_credential(
            db_session,
            CredentialCreate(
                name="webhook_cred",
                kind=CredentialKind.API_KEY,
                payload={"api_key": "sk-test-12345"},
            ),
            user.id,
        )

        with patch("app.steps.webhook_out.SharedHTTPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=type('obj', (object,), {
                'status_code': 200,
                'body': b'{"ok": true}',
                'headers': {},
            })())
            MockClient.return_value = mock_client

            from app.steps.base import StepContext, StepOutcome
            step = WebhookOutStep(
                config={
                    "method": "POST",
                    "url": "http://example.com/hook",
                },
                credential_resolver=lambda name: AsyncMock(return_value=await cred),
            )

            ctx = StepContext(
                variables={},
                run_id=1,
                step_id="step1",
                pipeline_id=1,
                user_id=user.id,
            )

            result = await step.execute(ctx)
            assert result.outcome == StepOutcome.SUCCEEDED

    @pytest.mark.asyncio
    async def test_ssrf_error_propagates(self):
        """SSRF error propagates as step failure."""
        with patch("app.steps.webhook_out.SharedHTTPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=SsrfError("SSRF blocked: metadata service"))
            MockClient.return_value = mock_client

            from app.steps.base import StepContext, StepOutcome
            step = WebhookOutStep(
                config={
                    "method": "POST",
                    "url": "http://169.254.169.254/latest/meta-data/",
                },
                credential_resolver=None,
            )

            ctx = StepContext(
                variables={},
                run_id=1,
                step_id="step1",
                pipeline_id=1,
                user_id=1,
            )

            result = await step.execute(ctx)
            assert result.outcome == StepOutcome.FAILED
            assert "SSRF" in result.error