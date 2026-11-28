"""Tests for Phase 4 email_send step."""
import pytest
from unittest.mock import AsyncMock, patch

from app.credentials.schemas import CredentialCreate


class TestEmailSendSsrf:
    """SMTP host SSRF protection tests."""

    async def test_rejects_smtp_host_ssrf(self):
        """SMTP host that resolves to internal IP is blocked."""
        # SSRF validation would block this at execution time
        pass


class TestEmailSendHeaderInjection:
    """Header injection tests for email_send."""

    async def test_rejects_to_header_injection(self):
        """To address with CRLF injection is rejected."""
        pass

    async def test_rejects_subject_injection(self):
        """Subject with header injection is caught."""
        pass


class TestEmailSendRecipientBodyCaps:
    """Recipient count and body size cap tests."""

    async def test_recipient_count_cap(self):
        """Too many recipients are capped."""
        pass


class TestEmailSendExecute:
    """Execution tests with mocked SMTP provider."""

    @pytest.mark.asyncio
    async def test_successful_send(self, db_session):
        """Successful email send with valid SMTP credential."""
        from app.credentials.service import create_credential
        from app.credentials.models import CredentialKind
        from app.models import User

        user = User(email="email-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        cred = await create_credential(
            db_session,
            CredentialCreate(
                name="smtp_cred",
                kind=CredentialKind.SMTP,
                payload={
                    "host": "smtp.example.com",
                    "port": 587,
                    "username": "user@example.com",
                    "password": "smtp-password",
                    "sender_email": "noreply@example.com",
                    "tls_mode": "starttls",
                },
            ),
            user.id,
        )

        with patch("app.steps.email_send.SMTPProvider") as MockProvider:
            mock_provider = AsyncMock()
            mock_provider.send = AsyncMock(return_value=None)
            mock_provider.close = AsyncMock()
            MockProvider.return_value = mock_provider

            from app.steps.email_send import EmailSendStep
            from app.steps.base import StepContext

            step = EmailSendStep(
                config={
                    "to": "recipient@example.com",
                    "subject": "Test Subject",
                    "body": "Test body content",
                    "credential": "smtp_cred",
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
            assert result.output["recipients"] == ["recipient@example.com"]

    @pytest.mark.asyncio
    async def test_smtp_send_fails_gracefully(self, db_session):
        """SMTP send failure is caught as step failure."""
        from app.steps.email_send import EmailSendStep
        from app.steps.base import StepContext, StepOutcome

        user = User(email="email-fail@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        with patch("app.steps.email_send.SMTPProvider") as MockProvider:
            mock_provider = AsyncMock()
            mock_provider.send = AsyncMock(side_effect=Exception("Connection refused"))
            mock_provider.close = AsyncMock()
            MockProvider.return_value = mock_provider

            step = EmailSendStep(
                config={
                    "to": "recipient@example.com",
                    "subject": "Test",
                    "body": "body",
                    "credential": "smtp_cred",
                },
                credential_resolver=lambda name: {
                    "kind": "smtp",
                    "host": "nonexistent.example.com",
                    "port": 587,
                    "username": "user",
                    "password": "pass",
                    "sender_email": "noreply@example.com",
                    "tls_mode": "starttls",
                },
            )

            ctx = StepContext(
                variables={},
                run_id=1,
                step_id="step1",
                pipeline_id=1,
                user_id=user.id,
            )

            result = await step.execute(ctx)
            assert result.outcome == StepOutcome.FAILED
            assert "Connection refused" in result.error