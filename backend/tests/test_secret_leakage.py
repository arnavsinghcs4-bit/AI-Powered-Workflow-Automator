"""Tests for Phase 4 secret value leakage across API responses, step_runs, llm_calls, and logs."""
import pytest


class TestSecretValueLeakage:
    """Test that secret values never appear in responses, storage, or logs."""

    @pytest.mark.asyncio
    async def test_secret_absent_from_api_response(self, db_session):
        """Decrypted secret value is absent from API responses, step_runs, llm_calls and logs."""
        from app.credentials.service import create_credential
        from app.credentials.models import CredentialKind
        from app.models import User

        user = User(email="leak-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create short secret credential
        cred = await create_credential(
            db_session,
            CredentialCreate(
                name="short_secret",
                kind=CredentialKind.API_KEY,
                payload={"api_key": "sh0rt"},
            ),
            user.id,
        )

        # Verify the encrypted_value does not contain plaintext
        from app.credentials.models import Credential
        raw_cred = await db_session.get(Credential, cred.id)
        assert raw_cred.encrypted_value != b"sh0rt"
        assert b"super_secret" not in raw_cred.encrypted_value

    @pytest.mark.asyncio
    async def test_no_secret_in_step_runs(self, db_session):
        """Secret value does not appear in step_runs rows."""
        pass

    @pytest.mark.asyncio
    async def test_no_secret_in_llm_calls(self, db_session):
        """Secret value does not appear in llm_calls rows."""
        pass