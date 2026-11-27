"""Tests for Phase 4 llm_extract step."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.steps.llm_extract import LLMExtractStep
from app.steps.base import StepContext, StepOutcome, StepResult


class TestLLMExtractSchemaValidation:
    """JSON schema validation tests."""

    @pytest.mark.asyncio
    async def test_invalid_json_schema_raises(self):
        """Missing json_schema raises ValueError in config."""
        with pytest.raises(ValueError, match="config.json_schema is required"):
            LLMExtractStep(
                config={"prompt": "test", "credential": "cred"},
                # json_schema intentionally omitted
            )

    @pytest.mark.asyncio
    async test_invalid_prompt_raises(self):
        """Missing prompt raises ValueError in config."""
        with pytest.raises(ValueError, match="config.prompt is required"):
            LLMExtractStep(
                config={"json_schema": {"type": "object"}, "credential": "cred"},
                # prompt intentionally omitted
            )


class TestLLMExtractRetry:
    """Retry and token budget tests."""

    @pytest.mark.asyncio
    async def test_token_budget_exceeded(self, db_session):
        """Step fails when token budget is exceeded."""
        from app.credentials.service import create_credential
        from app.credentials.models import CredentialKind

        # Create user
        user = User(email="budget-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create credential with low token budget
        cred = await create_credential(
            db_session,
            CredentialCreate(
                name="budget_cred",
                kind=CredentialKind.API_KEY,
                payload={"api_key": "sk-test", "model": "claude-3-haiku-20240307"},
            ),
            user.id,
        )

        step = LLMExtractStep(
            config={
                "prompt": "Extract all information from this text.",
                "json_schema": {"type": "object"},
                "credential": "budget_cred",
                "token_budget": 10,  # Very low budget
                "max_tokens": 100,
            },
            credential_resolver=lambda name: await cred,
            user_id=user.id,
            step_run_id=1,
        )

        ctx = StepContext(
            variables={},
            run_id=1,
            step_id="step1",
            pipeline_id=1,
            user_id=user.id,
        )

        # With budget=10 and estimated input tokens, should exceed budget
        result = await step.execute(ctx)
        assert result.outcome == StepOutcome.FAILED
        assert "budget" in result.error.lower()


class TestLLMExtractPerRunBudget:
    """Per-run token budget summed from llm_calls by run_id."""

    @pytest.mark.asyncio
    async def test_llm_calls_summed_by_run_id(self, db_session):
        """Token usage is tracked per run_id in llm_calls table."""
        from app.credentials.service import record_llm_call, get_llm_token_usage
        from app.models import User

        user = User(email="budget-run@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Record multiple LLM calls for same run_id
        await record_llm_call(
            step_run_id=1,
            user_id=user.id,
            provider="anthropic",
            model="claude-3-haiku-20240307",
            input_tokens=50,
            output_tokens=25,
            latency_ms=100,
            status="succeeded",
        )
        await record_llm_call(
            step_run_id=1,
            user_id=user.id,
            provider="anthropic",
            model="claude-3-haiku-20240307",
            input_tokens=100,
            output_tokens=50,
            latency_ms=200,
            status="succeeded",
        )

        # Sum should be (50+25) + (100+50) = 225
        usage = await get_llm_token_usage(db_session, user.id)
        assert usage == 225


class TestLLMExtractExecute:
    """Execution tests with mocked LLM provider."""

    @pytest.mark.asyncio
    async def test_successful_extract(self, db_session):
        """Successful LLM extraction with valid credential."""
        from app.credentials.service import create_credential
        from app.credentials.models import CredentialKind

        # Create user
        user = User(email="extract-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        cred = await create_credential(
            db_session,
            CredentialCreate(
                name="extract_cred",
                kind=CredentialKind.API_KEY,
                payload={"api_key": "sk-test-12345", "model": "claude-3-haiku-20240307"},
            ),
            user.id,
        )

        step = LLMExtractStep(
            config={
                "prompt": "Extract the key-value pairs from the text.",
                "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                "credential": "extract_cred",
            },
            credential_resolver=lambda name: await cred,
            user_id=user.id,
            step_run_id=1,
        )

        ctx = StepContext(
            variables={},
            run_id=1,
            step_id="step1",
            pipeline_id=1,
            user_id=user.id,
        )

        with patch("app.steps.llm_extract.AnthropicProvider") as MockProvider:
            mock_provider = AsyncMock()
            mock_provider.complete = AsyncMock(return_value=MagicMock(
                output={"name": "Test Value"},
                input_tokens=50,
                output_tokens=25,
            ))
            mock_provider.close = AsyncMock()
            MockProvider.return_value = mock_provider

            result = await step.execute(ctx)
            assert result.outcome == StepOutcome.SUCCEEDED
            assert result.output["extracted"] == {"name": "Test Value"}
            assert result.output["input_tokens"] == 50
            assert result.output["output_tokens"] == 25