"""Tests for Phase 4 secrets management - credentials and llm_calls."""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.models import Credential, LLMCall
from app.credentials.schemas import (
    CredentialCreate,
    CredentialUpdate,
    CredentialListItem,
    CREDENTIAL_PAYLOAD_SCHEMAS,
    CredentialKind,
    validate_credential_name,
)
from app.credentials.service import (
    create_credential,
    get_credential,
    get_credential_by_name,
    decrypt_credential,
    list_credentials,
    update_credential,
    delete_credential,
    get_llm_token_usage,
    record_llm_call,
    get_encryption,
)
from app.models import User
from app.pipelines.models import Pipeline, PipelineVersion, Run


class TestCredentialCRUDWithUserIsolation:
    """Test CRUD operations for credentials with user isolation."""

    @pytest.mark.asyncio
    async def test_create_api_key_credential(self, db_session: AsyncSession):
        """Test creating an API key credential."""
        user = User(email="cred-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        payload = CredentialCreate(
            name="my_api_key",
            kind=CredentialKind.API_KEY,
            payload={"api_key": "sk-test-secret-key-12345"},
        )
        cred = await create_credential(db_session, payload, user.id)
        assert cred.id is not None
        assert cred.name == "my_api_key"
        assert cred.kind == CredentialKind.API_KEY

    @pytest.mark.asyncio
    async def test_create_smtp_credential(self, db_session: AsyncSession):
        """Test creating an SMTP credential."""
        user = User(email="smtp-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        payload = CredentialCreate(
            name="smtp_config",
            kind=CredentialKind.SMTP,
            payload={
                "host": "smtp.example.com",
                "port": 587,
                "username": "user@example.com",
                "password": "smtp-password",
                "sender_email": "noreply@example.com",
                "tls_mode": "starttls",
            },
        )
        cred = await create_credential(db_session, payload, user.id)
        assert cred.kind == CredentialKind.SMTP

    @pytest.mark.asyncio
    async def test_create_bearer_credential(self, db_session: AsyncSession):
        """Test creating a bearer token credential."""
        user = User(email="bearer-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        payload = CredentialCreate(
            name="bearer_token",
            kind=CredentialKind.BEARER,
            payload={"token": "Bearer abc123def456"},
        )
        cred = await create_credential(db_session, payload, user.id)
        assert cred.kind == CredentialKind.BEARER

    @pytest.mark.asyncio
    async def test_create_basic_credential(self, db_session: AsyncSession):
        """Test creating a basic auth credential."""
        user = User(email="basic-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        payload = CredentialCreate(
            name="basic_auth",
            kind=CredentialKind.BASIC,
            payload={"username": "user", "password": "pass"},
        )
        cred = await create_credential(db_session, payload, user.id)
        assert cred.kind == CredentialKind.BASIC

    @pytest.mark.asyncio
    async def test_duplicate_name_raises(self, db_session: AsyncSession):
        """Test that duplicate credential names are rejected."""
        user = User(email="dup-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        payload1 = CredentialCreate(
            name="duplicate",
            kind=CredentialKind.API_KEY,
            payload={"api_key": "key1"},
        )
        await create_credential(db_session, payload1, user.id)

        payload2 = CredentialCreate(
            name="duplicate",
            kind=CredentialKind.API_KEY,
            payload={"api_key": "key2"},
        )
        with pytest.raises(Exception) as exc_info:
            await create_credential(db_session, payload2, user.id)
        assert "already exists" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cross_user_access_returns_404(self, db_session: AsyncSession):
        """Test that user1 cannot access user2's credential - returns CredentialNotFound."""
        user1 = User(email="user1-secrets@example.com", password_hash="$2b$12$test")
        user2 = User(email="user2-secrets@example.com", password_hash="$2b$12$test")
        db_session.add_all([user1, user2])
        await db_session.commit()
        await db_session.refresh(user1)
        await db_session.refresh(user2)

        payload = CredentialCreate(
            name="user1_cred",
            kind=CredentialKind.API_KEY,
            payload={"api_key": "secret-value"},
        )
        cred = await create_credential(db_session, payload, user1.id)

        # User 2 tries to access - should fail with CredentialNotFound
        with pytest.raises(Exception) as exc_info:
            await get_credential(db_session, cred.id, user2.id)
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_list_credentials_no_values(self, db_session: AsyncSession):
        """Test that list_credentials never returns credential values."""
        user = User(email="list-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create a credential with a short secret
        payload = CredentialCreate(
            name="test_secret",
            kind=CredentialKind.API_KEY,
            payload={"api_key": "sh0rt"},  # Short secret to test redaction
        )
        cred = await create_credential(db_session, payload, user.id)

        creds = await list_credentials(db_session, user.id)
        assert len(creds) == 1
        # Verify no credential value in response
        cred_dict = creds[0].model_dump()
        assert "encrypted_value" not in cred_dict
        assert "api_key" not in cred_dict
        assert "payload" not in cred_dict

    @pytest.mark.asyncio
    async def test_get_credential_in_response(self, db_session: AsyncSession):
        """Test that get_credential never returns the decrypted value in response."""
        user = User(email="get-response@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        payload = CredentialCreate(
            name="secret_key",
            kind=CredentialKind.BEARER,
            payload={"token": "Bearer very_secret_token_12345"},
        )
        cred = await create_credential(db_session, payload, user.id)

        # Get returns CredentialInDB which should NOT include decrypted payload
        result = await get_credential(db_session, cred.id, user.id)
        assert result.name == "secret_key"
        # The decrypted value should NOT be in the response model
        assert not hasattr(result, "payload") or result.payload is None

    @pytest.mark.asyncio
    async def test_decrypt_credential_returns_actual_value(self, db_session: AsyncSession):
        """Test that decrypt_credential returns the actual value."""
        user = User(email="decrypt-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        secret_value = "my_super_secret_api_key_12345"
        payload = CredentialCreate(
            name="test_decrypt",
            kind=CredentialKind.API_KEY,
            payload={"api_key": secret_value},
        )
        cred = await create_credential(db_session, payload, user.id)

        # Decrypt should return actual value
        decrypted = await decrypt_credential(db_session, cred.id, user.id)
        assert decrypted["api_key"] == secret_value

    @pytest.mark.asyncio
    async def test_encryption_round_trip(self, db_session: AsyncSession):
        """Test that encrypted value is NOT stored in plaintext."""
        user = User(email="roundtrip@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        secret = "super_secret_value_to_test_encryption_round_trip"
        payload = CredentialCreate(
            name="roundtrip_cred",
            kind=CredentialKind.API_KEY,
            payload={"api_key": secret},
        )
        cred = await create_credential(db_session, payload, user.id)

        # Reload from database to check raw storage
        raw_cred = await db_session.get(Credential, cred.id)
        # The encrypted_value should NOT contain the plaintext
        assert raw_cred.encrypted_value != secret.encode()
        assert b"super_secret" not in raw_cred.encrypted_value

        # But decrypt should get it back
        decrypted = await decrypt_credential(db_session, cred.id, user.id)
        assert decrypted["api_key"] == secret

    @pytest.mark.asyncio
    async def test_key_rotation(self, db_session: AsyncSession):
        """Test that credential rotation works with encryption."""
        user = User(email="rotate@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        payload = CredentialCreate(
            name="rotate_cred",
            kind=CredentialKind.BEARER,
            payload={"token": "old_token_123"},
        )
        cred = await create_credential(db_session, payload, user.id)

        # Rotate the token
        update_payload = CredentialUpdate(payload={"token": "new_token_456"})
        updated = await update_credential(db_session, cred.id, user.id, update_payload)

        # Verify new token works after decrypt
        decrypted = await decrypt_credential(db_session, cred.id, user.id)
        assert decrypted["token"] == "new_token_456"


class TestLLMTokenBudget:
    """Test LLM token budget tracking."""

    @pytest.mark.asyncio
    async def test_record_llm_call(self, db_session: AsyncSession):
        """Test recording an LLM call."""
        user = User(email="budget-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create a real run and step_run to link to
        pipeline = Pipeline(user_id=user.id, name="test-pipeline", description="test")
        db_session.add(pipeline)
        await db_session.commit()
        await db_session.refresh(pipeline)

        version = PipelineVersion(pipeline_id=pipeline.id, version_number=1, definition={})
        db_session.add(version)
        await db_session.commit()
        await db_session.refresh(version)

        run = Run(
            user_id=user.id,
            pipeline_id=pipeline.id,
            version_id=version.id,
            status="running",
        )
        db_session.add(run)
        await db_session.commit()
        await db_session.refresh(run)

        from app.pipelines.models import StepRun
        step_run = StepRun(
            run_id=run.id,
            node_id="step1",
            step_type="llm_extract",
            status="running",
            attempt=1,
        )
        db_session.add(step_run)
        await db_session.commit()
        await db_session.refresh(step_run)

        call = await record_llm_call(
            db=db_session,
            step_run_id=step_run.id,
            user_id=user.id,
            provider="anthropic",
            model="claude-3-haiku-20240307",
            input_tokens=100,
            output_tokens=50,
            latency_ms=500,
            status="succeeded",
        )
        assert call.id is not None
        assert call.provider == "anthropic"
        assert call.input_tokens == 100
        assert call.output_tokens == 50
        assert call.status == "succeeded"

    @pytest.mark.asyncio
    async def test_token_usage_sum_by_user(self, db_session: AsyncSession):
        """Test that token usage sums correctly for a user."""
        user = User(email="usage-sum@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create pipeline/version/run/step_run for proper linking
        pipeline = Pipeline(user_id=user.id, name="test-pipeline2", description="test")
        db_session.add(pipeline)
        await db_session.commit()
        await db_session.refresh(pipeline)

        version = PipelineVersion(pipeline_id=pipeline.id, version_number=1, definition={})
        db_session.add(version)
        await db_session.commit()
        await db_session.refresh(version)

        run = Run(
            user_id=user.id,
            pipeline_id=pipeline.id,
            version_id=version.id,
            status="running",
        )
        db_session.add(run)
        await db_session.commit()
        await db_session.refresh(run)

        from app.pipelines.models import StepRun
        step_run1 = StepRun(run_id=run.id, node_id="step1", step_type="llm_extract", status="succeeded", attempt=1)
        step_run2 = StepRun(run_id=run.id, node_id="step2", step_type="llm_extract", status="succeeded", attempt=1)
        step_run3 = StepRun(run_id=run.id, node_id="step3", step_type="llm_extract", status="failed", attempt=1)
        db_session.add_all([step_run1, step_run2, step_run3])
        await db_session.commit()
        await db_session.refresh(step_run1)
        await db_session.refresh(step_run2)
        await db_session.refresh(step_run3)

        # Record multiple calls
        await record_llm_call(
            db=db_session,
            step_run_id=step_run1.id,
            user_id=user.id,
            provider="anthropic",
            model="claude-3-haiku",
            input_tokens=100,
            output_tokens=50,
            latency_ms=100,
            status="succeeded",
        )
        await record_llm_call(
            db=db_session,
            step_run_id=step_run2.id,
            user_id=user.id,
            provider="anthropic",
            model="claude-3-haiku",
            input_tokens=200,
            output_tokens=100,
            latency_ms=200,
            status="succeeded",
        )
        await record_llm_call(
            db=db_session,
            step_run_id=step_run3.id,
            user_id=user.id,
            provider="anthropic",
            model="claude-3-haiku",
            input_tokens=50,
            output_tokens=25,
            latency_ms=50,
            status="failed",
        )

        usage = await get_llm_token_usage(db_session, user.id)
        # Should sum all input + output tokens
        assert usage == (100 + 50) + (200 + 100) + (50 + 25)  # 525 total


class TestCredentialValueLeakage:
    """Test that credential values never leak in responses, logs, or storage."""

    @pytest.mark.asyncio
    async def test_value_not_in_db_response(self, db_session: AsyncSession):
        """Test that decrypted credential values are not in DB responses."""
        user = User(email="leak-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        secret = "short_leaked_secret"
        payload = CredentialCreate(
            name="leak_test",
            kind=CredentialKind.API_KEY,
            payload={"api_key": secret},
        )
        cred = await create_credential(db_session, payload, user.id)

        from app.execution.serializers import redact
        response = await get_credential(db_session, cred.id, user.id)
        response_dict = response.model_dump()

        # Redact should catch any secrets
        redacted = redact(response_dict)
        assert secret not in str(redacted)

    @pytest.mark.asyncio
    async def test_llm_call_stores_only_metadata(self, db_session: AsyncSession):
        """Test that llm_calls table stores tokens, not actual prompts or responses."""
        user = User(email="llm-leak-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create a proper pipeline/version/run/step_run for linking
        pipeline = Pipeline(user_id=user.id, name="test-pipeline-meta", description="test")
        db_session.add(pipeline)
        await db_session.commit()
        await db_session.refresh(pipeline)

        version = PipelineVersion(pipeline_id=pipeline.id, version_number=1, definition={})
        db_session.add(version)
        await db_session.commit()
        await db_session.refresh(version)

        run = Run(
            user_id=user.id,
            pipeline_id=pipeline.id,
            version_id=version.id,
            status="running",
        )
        db_session.add(run)
        await db_session.commit()
        await db_session.refresh(run)

        from app.pipelines.models import StepRun
        step_run = StepRun(
            run_id=run.id,
            node_id="step1",
            step_type="llm_extract",
            status="running",
            attempt=1,
        )
        db_session.add(step_run)
        await db_session.commit()
        await db_session.refresh(step_run)

        await record_llm_call(
            db=db_session,
            step_run_id=step_run.id,
            user_id=user.id,
            provider="anthropic",
            model="claude-3-haiku",
            input_tokens=150,
            output_tokens=75,
            latency_ms=300,
            status="succeeded",
        )

        # Query raw llm_calls - should only have metadata, not actual content
        calls = await db_session.execute(select(LLMCall).where(LLMCall.user_id == user.id))
        call = calls.scalar_one()
        call_dict = call.__dict__

        # Should not have fields for actual prompt/response content
        assert "prompt" not in call_dict
        assert "response" not in call_dict
        assert "api_key" not in call_dict

        # Should have token counts
        assert call.input_tokens == 150
        assert call.output_tokens == 75