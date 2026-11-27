"""Tests for Phase 4: {{secrets.x}} used outside step credential field."""
import pytest
from fastapi import status


class TestSecretsOutsideStep:
    """Test that {{secrets.x}} outside step credential fields returns 422."""

    @pytest.mark.asyncio
    async def test_secrets_ref_outside_step_returns_422(self, client, db_session):
        """POST /pipelines with {{secrets.x}} outside a step's credential field returns 422."""
        from app.models import User
        from app.pipelines.schemas import PipelineCreate

        # Create user
        user = User(email="test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Try to create pipeline with {{secrets.x}} in config outside a step
        pipeline = PipelineCreate(
            name="test-pipeline",
            description="pipeline with secrets outside step",
            definition={
                "nodes": [
                    {
                        "id": "step1",
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://example.com",
                            # {{secrets.x}} outside of a step credential field
                            "headers": {
                                "Authorization": "{{secrets.API_KEY}}"  # Not inside step credential
                            }
                        }
                    }
                ]
            },
        )

        from app.main import app
        from httpx import AsyncClient as _AsyncClient
        from fastapi.dependency_deps import _get_dependencies

        response = await client.post(
            "/pipelines",
            json=pipeline.dict(),
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY