"""Tests for Phase 4: {{secrets.x}} used outside step credential field."""
import pytest
from fastapi import status


class TestSecretsOutsideStep:
    """Test that {{secrets.x}} outside step credential fields returns 422."""

    @pytest.mark.asyncio
    async def test_secrets_ref_outside_step_returns_422(self, db_session):
        """POST /pipelines with {{secrets.x}} outside a step's credential field returns 422."""
        from app.models import User
        from app.pipelines.schemas import PipelineCreate
        from app.steps.base import StepContext, StepOutcome

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
                            "headers": {
                                "Authorization": "{{secrets.API_KEY}}"
                            }
                        }
                    }
                ]
            },
        )

        # Using ORM to validate the pipeline - should fail
        # The secrets.x template outside credential field should trigger validation
        from app.pipelines.routes import create_pipeline
        from app.main import app

        with app.test_client() as client:
            response = client.post(
                "/pipelines",
                json=pipeline.dict(),
            )
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY