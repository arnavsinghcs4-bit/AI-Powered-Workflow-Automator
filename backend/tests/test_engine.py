"""Worker execution engine integration tests - Phase 3 Celery tasks."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.pipelines.models import Pipeline, PipelineVersion, Run, StepRun
from app.worker.tasks import submit_run


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """Create a test user."""
    user = User(email="worker-test@example.com", password_hash="$2b$12$test")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def pipeline_with_version(db_session: AsyncSession, test_user: User):
    """Create a pipeline with a version containing http_request step."""
    pipeline = Pipeline(
        user_id=test_user.id,
        name="Test Pipeline",
        description="For worker tests",
    )
    db_session.add(pipeline)
    await db_session.flush()

    version = PipelineVersion(
        pipeline_id=pipeline.id,
        version_number=1,
        definition={
            "nodes": [
                {
                    "id": "step1",
                    "type": "http_request",
                    "config": {
                        "method": "GET",
                        "url": "http://api.example.com/data",
                    },
                }
            ]
        },
    )
    db_session.add(version)
    await db_session.commit()
    await db_session.refresh(pipeline)
    await db_session.refresh(version)
    return {"pipeline": pipeline, "version": version}


@pytest.fixture
async def pending_run(db_session: AsyncSession, test_user: User, pipeline_with_version: dict):
    """Create a pending run with step_runs."""
    pipeline = pipeline_with_version["pipeline"]
    version = pipeline_with_version["version"]

    run = Run(
        pipeline_id=pipeline.id,
        version_id=version.id,
        user_id=test_user.id,
        status="pending",
        trigger_type="manual",
    )
    db_session.add(run)
    await db_session.flush()

    step_run = StepRun(
        run_id=run.id,
        node_id="step1",
        step_type="http_request",
        status="pending",
        attempt=1,
        input={},
    )
    db_session.add(step_run)
    await db_session.commit()
    await db_session.refresh(run)
    await db_session.refresh(step_run)
    return {"run": run, "step_run": step_run, "pipeline": pipeline, "version": version}


class TestSubmitRunTask:
    """Celery submit_run task tests."""

    def _make_mock_client(self, responses: list):
        """Create a mock client factory that returns responses in sequence."""
        call_count = {"count": 0}

        async def mock_client_factory():
            class MockClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

                async def request(self, method, url, headers=None, json=None):
                    call_count["count"] += 1
                    idx = min(call_count["count"] - 1, len(responses) - 1)
                    resp = responses[idx]
                    response = MagicMock()
                    response.status_code = resp.get("status", 200)
                    response.headers = resp.get("headers", {"content-type": "application/json"})
                    response.text = resp.get("body", '{"ok": true}')
                    return response

            return MockClient()

        return mock_client_factory, call_count

    async def test_submit_run_success(self, db_session: AsyncSession, pending_run: dict):
        """Test successful run execution."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client([{"status": 200, "body": '{"result": "ok"}'}])

        with patch("app.steps.registry.step_types") as mock_step_types:
            from app.steps.http_request import HttpRequestStep
            mock_step_types.return_value = {"http_request": HttpRequestStep}

            submit_run(
                run_id=run.id,
                steps_data={"step1": {"type": "http_request", "config": {"method": "GET", "url": "http://api.example.com/data"}}},
                definition=version.definition,
            )

        # Verify run is succeeded
        result = await db_session.execute(select(Run).where(Run.id == run.id))
        run_row = result.scalar_one()
        assert run_row.status == "succeeded"
        assert run_row.finished_at is not None

        # Verify step_run is succeeded with output
        result = await db_session.execute(select(StepRun).where(StepRun.id == step_run.id))
        sr = result.scalar_one()
        assert sr.status == "succeeded"
        assert sr.output is not None
        assert sr.output["status"] == 200
        assert sr.output["body"] == '{"result": "ok"}'

    async def test_submit_run_step_failure(self, db_session: AsyncSession, pending_run: dict):
        """Test run fails when step fails (non-retryable 500 with retries=0)."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client([{"status": 500, "body": "Internal Server Error"}])

        with patch("app.steps.registry.step_types") as mock_step_types:
            from app.steps.http_request import HttpRequestStep
            mock_step_types.return_value = {"http_request": HttpRequestStep}

            submit_run(
                run_id=run.id,
                steps_data={"step1": {"type": "http_request", "config": {"method": "GET", "url": "http://api.example.com/data", "retries": 0}}},
                definition=version.definition,
            )

        result = await db_session.execute(select(Run).where(Run.id == run.id))
        run_row = result.scalar_one()
        assert run_row.status == "failed"

        result = await db_session.execute(select(StepRun).where(StepRun.id == step_run.id))
        sr = result.scalar_one()
        assert sr.status == "failed"
        assert sr.error is not None

    async def test_submit_run_retry_then_success(self, db_session: AsyncSession, pending_run: dict):
        """Test retry logic: first attempt fails (500), second succeeds (200)."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client([
            {"status": 500, "body": "Server Error"},
            {"status": 200, "body": '{"ok": true}'},
        ])

        with patch("app.steps.registry.step_types") as mock_step_types:
            from app.steps.http_request import HttpRequestStep
            mock_step_types.return_value = {"http_request": HttpRequestStep}

            submit_run(
                run_id=run.id,
                steps_data={"step1": {"type": "http_request", "config": {"method": "GET", "url": "http://api.example.com/data", "retries": 1}}},
                definition=version.definition,
            )

        assert call_count["count"] == 2  # Initial + 1 retry

        result = await db_session.execute(select(Run).where(Run.id == run.id))
        run_row = result.scalar_one()
        assert run_row.status == "succeeded"

        result = await db_session.execute(select(StepRun).where(StepRun.id == step_run.id))
        sr = result.scalar_one()
        assert sr.status == "succeeded"

    async def test_submit_run_retry_exhausted(self, db_session: AsyncSession, pending_run: dict):
        """Test all retries exhausted -> run fails."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client([
            {"status": 500, "body": "Server Error"},
            {"status": 500, "body": "Server Error"},
            {"status": 500, "body": "Server Error"},
        ])

        with patch("app.steps.registry.step_types") as mock_step_types:
            from app.steps.http_request import HttpRequestStep
            mock_step_types.return_value = {"http_request": HttpRequestStep}

            submit_run(
                run_id=run.id,
                steps_data={"step1": {"type": "http_request", "config": {"method": "GET", "url": "http://api.example.com/data", "retries": 2}}},
                definition=version.definition,
            )

        assert call_count["count"] == 3  # Initial + 2 retries

        result = await db_session.execute(select(Run).where(Run.id == run.id))
        run_row = result.scalar_one()
        assert run_row.status == "failed"

        result = await db_session.execute(select(StepRun).where(StepRun.id == step_run.id))
        sr = result.scalar_one()
        assert sr.status == "failed"

    async def test_submit_run_timeout(self, db_session: AsyncSession, pending_run: dict):
        """Test timeout handling (httpx.TimeoutException)."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        import httpx

        async def mock_client_factory():
            class MockClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

                async def request(self, method, url, headers=None, json=None):
                    raise httpx.TimeoutException("Request timed out")

            return MockClient()

        with patch("app.steps.registry.step_types") as mock_step_types:
            from app.steps.http_request import HttpRequestStep
            mock_step_types.return_value = {"http_request": HttpRequestStep}

            submit_run(
                run_id=run.id,
                steps_data={"step1": {"type": "http_request", "config": {"method": "GET", "url": "http://api.example.com/data", "retries": 0}}},
                definition=version.definition,
            )

        result = await db_session.execute(select(Run).where(Run.id == run.id))
        run_row = result.scalar_one()
        assert run_row.status == "failed"

        result = await db_session.execute(select(StepRun).where(StepRun.id == step_run.id))
        sr = result.scalar_one()
        assert sr.status == "failed"
        assert "TimeoutException" in sr.error or "timeout" in sr.error.lower()

    async def test_submit_run_double_delivery(self, db_session: AsyncSession, pending_run: dict):
        """Test idempotent re-delivery: submitting same run twice."""
        run = pending_run["run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client([{"status": 200, "body": '{"ok": true}'}])

        with patch("app.steps.registry.step_types") as mock_step_types:
            from app.steps.http_request import HttpRequestStep
            mock_step_types.return_value = {"http_request": HttpRequestStep}

            # First delivery
            submit_run(
                run_id=run.id,
                steps_data={"step1": {"type": "http_request", "config": {"method": "GET", "url": "http://api.example.com/data"}}},
                definition=version.definition,
            )

            # Second delivery (should be no-op because run is no longer pending)
            submit_run(
                run_id=run.id,
                steps_data={"step1": {"type": "http_request", "config": {"method": "GET", "url": "http://api.example.com/data"}}},
                definition=version.definition,
            )

        result = await db_session.execute(select(Run).where(Run.id == run.id))
        run_row = result.scalar_one()
        assert run_row.status == "succeeded"

    async def test_submit_run_stale_lease_reclaim(self, db_session: AsyncSession, pending_run: dict):
        """Test stale-run recovery: claim a run left in 'running' with old claimed_at."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        # Manually set run to running with old claimed_at (stale)
        run.status = "running"
        run.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await db_session.commit()

        mock_factory, call_count = self._make_mock_client([{"status": 200, "body": '{"recovered": true}'}])

        with patch("app.steps.registry.step_types") as mock_step_types:
            from app.steps.http_request import HttpRequestStep
            mock_step_types.return_value = {"http_request": HttpRequestStep}

            submit_run(
                run_id=run.id,
                steps_data={"step1": {"type": "http_request", "config": {"method": "GET", "url": "http://api.example.com/data"}}},
                definition=version.definition,
            )

        # Run should have been re-claimed and executed
        result = await db_session.execute(select(Run).where(Run.id == run.id))
        run_row = result.scalar_one()
        assert run_row.status == "succeeded"
        assert run_row.claimed_at is not None  # Updated on re-claim

        result = await db_session.execute(select(StepRun).where(StepRun.id == step_run.id))
        sr = result.scalar_one()
        assert sr.status == "succeeded"


class TestVersionCRUD:
    """Version CRUD operations within pipeline tests."""

    async def test_version_create_list(self, db_session: AsyncSession, test_user: User):
        """Test creating and listing versions."""
        pipeline = Pipeline(user_id=test_user.id, name="Version Test")
        db_session.add(pipeline)
        await db_session.flush()

        v1 = PipelineVersion(
            pipeline_id=pipeline.id, version_number=1, definition={"nodes": [{"id": "a"}]}
        )
        v2 = PipelineVersion(
            pipeline_id=pipeline.id, version_number=2, definition={"nodes": [{"id": "b"}]}
        )
        db_session.add_all([v1, v2])
        await db_session.commit()

        result = await db_session.execute(
            select(PipelineVersion)
            .where(PipelineVersion.pipeline_id == pipeline.id)
            .order_by(PipelineVersion.version_number.desc())
        )
        versions = result.scalars().all()
        assert len(versions) == 2
        assert versions[0].version_number == 2
        assert versions[1].version_number == 1


class TestCrossUserIsolation:
    """Cross-user isolation tests."""

    async def test_cross_user_pipeline_404(self, db_session: AsyncSession):
        """User A cannot access User B's pipeline."""
        user_a = User(email="usera@test.com", password_hash="$2b$12$test")
        user_b = User(email="userb@test.com", password_hash="$2b$12$test")
        db_session.add_all([user_a, user_b])
        await db_session.flush()

        pipeline = Pipeline(user_id=user_a.id, name="User A's Pipeline")
        db_session.add(pipeline)
        await db_session.commit()

        # User B tries to query User A's pipeline - should get empty result
        result = await db_session.execute(
            select(Pipeline).where(Pipeline.id == pipeline.id, Pipeline.user_id == user_b.id)
        )
        assert result.scalar_one_or_none() is None

    async def test_cross_user_run_404(self, db_session: AsyncSession, test_user: User):
        """User A cannot access User B's run."""
        user_b = User(email="userb@test.com", password_hash="$2b$12$test")
        db_session.add(user_b)
        await db_session.flush()

        pipeline = Pipeline(user_id=test_user.id, name="Test")
        db_session.add(pipeline)
        await db_session.flush()

        version = PipelineVersion(
            pipeline_id=pipeline.id, version_number=1, definition={"nodes": []}
        )
        db_session.add(version)
        await db_session.flush()

        run = Run(
            pipeline_id=pipeline.id,
            version_id=version.id,
            user_id=test_user.id,
            status="pending",
            trigger_type="manual",
        )
        db_session.add(run)
        await db_session.commit()

        # User B tries to query User A's run - should get empty result
        result = await db_session.execute(
            select(Run).where(Run.id == run.id, Run.user_id == user_b.id)
        )
        assert result.scalar_one_or_none() is None