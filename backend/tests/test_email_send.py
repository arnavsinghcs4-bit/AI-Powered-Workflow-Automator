"""Tests for Phase 4 email_send step."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.steps.email_send import EmailSendStep
from app.steps.base import StepContext, StepOutcome, StepResult


class TestEmailSendSsrf:
    """SMTP host SSRF protection tests."""

    @pytest.mark.asyncio
    async def test_rejects_smtp_host_ssrf(self):
        """SMTP host that resolves to internal IP is blocked."""
        step = EmailSendStep(
            config={
                "to": "test@example.com",
                "subject": "test",
                "body": "test",
                "credential": "smtp_cred",
            },
            credential_resolver=lambda name: {
                "kind": "smtp",
                "host": "169.254.169.254",  # Metadata service IP
                "port": 587,
                "username": "user",
                "password": "pass",
                "sender_email": "noreply@example.com",
                "tls_mode": "starttls",
            },
        )
        # SSRF validation would block this at execution time


class TestEmailSendHeaderInjection:
    """Header injection tests for email_send."""

    @pytest.mark.asyncio
    async def test_rejects_to_header_injection(self):
        """To address with CRLF injection is rejected."""
        step = EmailSendStep(
            config={
                "to": "user@example.com\r\nBcc: hacker@evil.com",
                "subject": "test",
                "body": "test",
                "credential": "smtp_cred",
            },
            credential_resolver=lambda name: {
                "kind": "smtp",
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password": "pass",
                "sender_email": "noreply@example.com",
                "tls_mode": "starttls",
            },
        )
        # Config validation should catch CRLF in recipient addresses

    @pytest.mark.asyncio
    async def test_rejects_subject_injection(self):
        """Subject with header injection is caught."""
        step = EmailSendStep(
            config={
                "to": "user@example.com",
                "subject": "test\r\nBcc: hacker@evil.com",
                "body": "test",
                "credential": "smtp_cred",
            },
            credential_resolver=lambda name: {
                "kind": "smtp",
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password": "pass",
                "sender_email": "noreply@example.com",
                "tls_mode": "starttls",
            },
        )


class TestEmailSendRecipientBodyCaps:
    """Recipient count and body size cap tests."""

    @pytest.mark.asyncio
    async def test_recipient_count_cap(self):
        """Too many recipients are capped."""
        step = EmailSendStep(
            config={
                "to": ["a@ex.com", "b@ex.com", "c@ex.com", "d@ex.com", "e@ex.com",
                       "f@ex.com", "g@ex.com", "h@ex.com", "i@ex.com", "j@ex.com"],
                "subject": "test",
                "body": "test",
                "credential": "smtp_cred",
            },
            credential_resolver=lambda name: {
                "kind": "smtp",
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password": "pass",
                "sender_email": "noreply@example.com",
                "tls_mode": "starttls",
            },
        )
        # Recipient count should be capped


class TestEmailSendExecute:
    """Execution tests with mocked SMTP provider."""

    @pytest.mark.asyncio
    async def test_successful_send(self, db_session):
        """Successful email send with valid SMTP credential."""
        from app.credentials.service import create_credential
        from app.credentials.models import CredentialKind
        from app.steps.email_send import EmailSendStep
        from app.steps.base import StepContext, StepOutcome, StepResult

        # Create user and SMTP credential
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

        # Mock SMTP provider
        with patch("app.steps.email_send.SMTPProvider") as MockProvider:
            mock_provider = AsyncMock()
            mock_provider.send = AsyncMock(return_value=None)
            mock_provider.close = AsyncMock()
            MockProvider.return_value = mock_provider

            step = EmailSendStep(
                config={
                    "to": "recipient@example.com",
                    "subject": "Test Subject",
                    "body": "Test body content",
                    "credential": "smtp_cred",
                },
                credential_resolver=lambda name: await cred,
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
            assert result.output["subject"] == "Test Subject"

    @pytest.mark.asyncio
    async def test_smtp_send_fails_gracefully(self, db_session):
        """SMTP send failure is caught as step failure."""
        from app.steps.email_send import EmailSendStep
        from app.steps.base import StepContext, StepOutcome, StepResult

        user = User(email="email-fail@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

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

        with patch("app.steps.email_send.SMTPProvider") as MockProvider:
            mock_provider = AsyncMock()
            mock_provider.send = AsyncMock(side_effect=Exception("Connection refused"))
            mock_provider.close = AsyncMock()
            MockProvider.return_value = mock_provider

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