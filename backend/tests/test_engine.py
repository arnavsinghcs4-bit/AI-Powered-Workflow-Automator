"""Worker execution engine integration tests - Phase 3 Celery tasks."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.pipelines.models import Pipeline, PipelineVersion, Run, StepRun


# Import submit_run first, then patch asyncio.run in the worker module
# to work with pytest-asyncio's running event loop
from app.worker.tasks import submit_run
import app.worker.tasks as worker_tasks
import asyncio
import threading

# Replace asyncio.run in the worker module with a version that works in tests
_original_worker_run = worker_tasks.asyncio.run


def _patched_worker_run(coro, *, debug=False):
    """Patch asyncio.run in worker module to run coroutine in a new event loop in a thread.

    This avoids the "event loop already running" error when tests are running
    in pytest-asyncio's event loop.
    """
    print(f"DEBUG _patched_worker_run: called with coro: {coro}")
    result_container = {"result": None, "exception": None}

    def run_in_thread():
        # Create a new event loop in this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if debug:
                loop.set_debug(True)
            result_container["result"] = loop.run_until_complete(coro)
        except Exception as e:
            result_container["exception"] = e
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            finally:
                loop.close()
                asyncio.set_event_loop(None)

    thread = threading.Thread(target=run_in_thread)
    thread.start()
    thread.join()

    if result_container["exception"]:
        raise result_container["exception"]
    return result_container["result"]


# Apply the patch to the worker module
worker_tasks.asyncio.run = _patched_worker_run
print(f"DEBUG: worker_tasks.asyncio.run = {worker_tasks.asyncio.run}")


@pytest.fixture
def submit_run_task(_patch_worker_db):
    """Get submit_run function with asyncio.run already patched and worker DB patched.

    This fixture imports submit_run AFTER the _patch_worker_db fixture has run,
    so the worker's sync_engine and _sync_session_maker are properly patched.
    """
    from app.worker.tasks import submit_run

    return submit_run


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
async def pending_run(
    db_session: AsyncSession, test_user: User, pipeline_with_version: dict
):
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
                    response.headers = resp.get(
                        "headers", {"content-type": "application/json"}
                    )
                    response.text = resp.get("body", '{"ok": true}')
                    return response

            return MockClient()

        return mock_client_factory, call_count

    async def test_submit_run_success(
        self, db_session: AsyncSession, pending_run: dict, submit_run_task
    ):
        """Test successful run execution."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client(
            [{"status": 200, "body": '{"result": "ok"}'}]
        )

        from app.steps.http_request import HttpRequestStep

        # Create a step instance with our mock factory
        mock_step = HttpRequestStep(
            {
                "method": "GET",
                "url": "http://api.example.com/data",
            },
            client_factory=mock_factory,
        )

        # Patch build_steps to return our mock step
        with patch("app.steps.registry.build_steps", return_value={"step1": mock_step}):
            import app.worker.tasks as wt

            print(f"DEBUG: wt.asyncio.run = {wt.asyncio.run}")
            print(f"DEBUG: wt._sync_session_maker = {wt._sync_session_maker}")
            print(f"DEBUG: wt.sync_engine = {wt.sync_engine}")
            # Also check if run exists in worker DB
            with wt._sync_session_maker() as session:
                from app.pipelines.models import Run, StepRun
                from sqlalchemy import select

                run_check = session.execute(
                    select(Run).where(Run.id == run.id)
                ).scalar_one_or_none()
                print(f"DEBUG: run in worker DB = {run_check}")
                if run_check:
                    step_check = (
                        session.execute(select(StepRun).where(StepRun.run_id == run.id))
                        .scalars()
                        .all()
                    )
                    print(f"DEBUG: step_runs in worker DB = {step_check}")

            # Patch asyncio.run to see if it's called
            original_patched = wt.asyncio.run

            def debug_patched(coro, *, debug=False):
                print(f"DEBUG: asyncio.run called with coro: {coro}")
                result = original_patched(coro, debug=debug)
                print(f"DEBUG: asyncio.run returned: {result}")
                return result

            wt.asyncio.run = debug_patched

            # Also patch _mark_step to see what's happening
            original_mark_step = wt._mark_step

            def debug_mark_step(step_run_id, status, output=None, error=None):
                print(
                    f"DEBUG: _mark_step called: step_run_id={step_run_id}, status={status}, output={output}, error={error}"
                )
                return original_mark_step(step_run_id, status, output, error)

            wt._mark_step = debug_mark_step

            # Also patch _mark_run
            original_mark_run = wt._mark_run

            def debug_mark_run(run_id, status, error=None):
                print(
                    f"DEBUG: _mark_run called: run_id={run_id}, status={status}, error={error}"
                )
                return original_mark_run(run_id, status, error)

            wt._mark_run = debug_mark_run

            submit_run_task.run(
                run_id=run.id,
                steps_data={
                    "step1": {
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://api.example.com/data",
                        },
                    }
                },
                definition=version.definition,
            )

            # Check DB after task completes
            with wt._sync_session_maker() as session:
                from app.pipelines.models import Run, StepRun
                from sqlalchemy import select

                run_check = session.execute(
                    select(Run).where(Run.id == run.id)
                ).scalar_one_or_none()
                print(
                    f"DEBUG AFTER: run in worker DB = {run_check}, status={run_check.status if run_check else 'None'}"
                )
                if run_check:
                    step_check = (
                        session.execute(select(StepRun).where(StepRun.run_id == run.id))
                        .scalars()
                        .all()
                    )
                    print(
                        f"DEBUG AFTER: step_runs in worker DB = {[(s.id, s.status, s.output) for s in step_check]}"
                    )

        # Verify run is succeeded (need to refresh because session has expire_on_commit=False)
        await db_session.refresh(run)
        assert run.status == "succeeded"
        assert run.finished_at is not None

        # Verify step_run is succeeded with output
        await db_session.refresh(step_run)
        assert step_run.status == "succeeded"
        assert step_run.output is not None
        assert step_run.output["status"] == 200
        assert step_run.output["body"] == '{"result": "ok"}'

    async def test_submit_run_step_failure(
        self, db_session: AsyncSession, pending_run: dict, submit_run_task
    ):
        """Test run fails when step fails (non-retryable 500 with retries=0)."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client(
            [{"status": 500, "body": "Internal Server Error"}]
        )

        from app.steps.http_request import HttpRequestStep

        # Create a step instance with our mock factory
        mock_step = HttpRequestStep(
            {
                "method": "GET",
                "url": "http://api.example.com/data",
                "retries": 0,
            },
            client_factory=mock_factory,
        )

        # Patch build_steps to return our mock step
        with patch("app.steps.registry.build_steps", return_value={"step1": mock_step}):
            submit_run(
                run_id=run.id,
                steps_data={
                    "step1": {
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://api.example.com/data",
                            "retries": 0,
                        },
                    }
                },
                definition=version.definition,
            )

        # Refresh objects since session has expire_on_commit=False
        await db_session.refresh(run)
        assert run.status == "failed"

        await db_session.refresh(step_run)
        assert step_run.status == "failed"
        assert step_run.error is not None

    async def test_submit_run_retry_then_success(
        self, db_session: AsyncSession, pending_run: dict, submit_run_task
    ):
        """Test retry logic: first attempt fails (500), second succeeds (200)."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client(
            [
                {"status": 500, "body": "Server Error"},
                {"status": 200, "body": '{"ok": true}'},
            ]
        )

        from app.steps.http_request import HttpRequestStep

        # Create a step instance with our mock factory
        mock_step = HttpRequestStep(
            {
                "method": "GET",
                "url": "http://api.example.com/data",
                "retries": 1,
            },
            client_factory=mock_factory,
        )

        # Patch build_steps to return our mock step
        with patch("app.steps.registry.build_steps", return_value={"step1": mock_step}):
            submit_run(
                run_id=run.id,
                steps_data={
                    "step1": {
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://api.example.com/data",
                            "retries": 1,
                        },
                    }
                },
                definition=version.definition,
            )

        assert call_count["count"] == 2  # Initial + 1 retry

        # Refresh objects since session has expire_on_commit=False
        await db_session.refresh(run)
        assert run.status == "succeeded"

        await db_session.refresh(step_run)
        assert step_run.status == "succeeded"

    async def test_submit_run_retry_exhausted(
        self, db_session: AsyncSession, pending_run: dict, submit_run_task
    ):
        """Test all retries exhausted -> run fails."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client(
            [
                {"status": 500, "body": "Server Error"},
                {"status": 500, "body": "Server Error"},
                {"status": 500, "body": "Server Error"},
            ]
        )

        from app.steps.http_request import HttpRequestStep

        # Create a step instance with our mock factory
        mock_step = HttpRequestStep(
            {
                "method": "GET",
                "url": "http://api.example.com/data",
                "retries": 2,
            },
            client_factory=mock_factory,
        )

        # Patch build_steps to return our mock step
        with patch("app.steps.registry.build_steps", return_value={"step1": mock_step}):
            submit_run(
                run_id=run.id,
                steps_data={
                    "step1": {
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://api.example.com/data",
                            "retries": 2,
                        },
                    }
                },
                definition=version.definition,
            )

        assert call_count["count"] == 3  # Initial + 2 retries

        # Refresh objects since session has expire_on_commit=False
        await db_session.refresh(run)
        assert run.status == "failed"

        await db_session.refresh(step_run)
        assert step_run.status == "failed"

    async def test_submit_run_timeout(
        self, db_session: AsyncSession, pending_run: dict, submit_run_task
    ):
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

        from app.steps.http_request import HttpRequestStep

        # Create a step instance with our mock factory
        mock_step = HttpRequestStep(
            {
                "method": "GET",
                "url": "http://api.example.com/data",
                "retries": 0,
            },
            client_factory=mock_client_factory,
        )

        # Patch build_steps to return our mock step
        with patch("app.steps.registry.build_steps", return_value={"step1": mock_step}):
            submit_run(
                run_id=run.id,
                steps_data={
                    "step1": {
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://api.example.com/data",
                            "retries": 0,
                        },
                    }
                },
                definition=version.definition,
            )

        # Refresh objects since session has expire_on_commit=False
        await db_session.refresh(run)
        assert run.status == "failed"

        await db_session.refresh(step_run)
        assert step_run.status == "failed"
        assert (
            "TimeoutException" in step_run.error or "timeout" in step_run.error.lower()
        )

    async def test_submit_run_double_delivery(
        self, db_session: AsyncSession, pending_run: dict, submit_run_task
    ):
        """Test idempotent re-delivery: submitting same run twice."""
        run = pending_run["run"]
        version = pending_run["version"]

        mock_factory, call_count = self._make_mock_client(
            [{"status": 200, "body": '{"ok": true}'}]
        )

        from app.steps.http_request import HttpRequestStep

        # Create a step instance with our mock factory
        mock_step = HttpRequestStep(
            {
                "method": "GET",
                "url": "http://api.example.com/data",
            },
            client_factory=mock_factory,
        )

        # Patch build_steps to return our mock step
        with patch("app.steps.registry.build_steps", return_value={"step1": mock_step}):
            # First delivery
            submit_run_task.run(
                run_id=run.id,
                steps_data={
                    "step1": {
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://api.example.com/data",
                        },
                    }
                },
                definition=version.definition,
            )

            # Second delivery (should be no-op because run is no longer pending)
            submit_run_task.run(
                run_id=run.id,
                steps_data={
                    "step1": {
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://api.example.com/data",
                        },
                    }
                },
                definition=version.definition,
            )

        # Refresh objects since session has expire_on_commit=False
        await db_session.refresh(run)
        assert run.status == "succeeded"

    async def test_submit_run_stale_lease_reclaim(
        self, db_session: AsyncSession, pending_run: dict, submit_run_task
    ):
        """Test stale-run recovery: claim a run left in 'running' with old claimed_at."""
        run = pending_run["run"]
        step_run = pending_run["step_run"]
        version = pending_run["version"]

        # Manually set run to running with old claimed_at (stale)
        run.status = "running"
        run.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await db_session.commit()

        mock_factory, call_count = self._make_mock_client(
            [{"status": 200, "body": '{"recovered": true}'}]
        )

        from app.steps.http_request import HttpRequestStep

        # Create a step instance with our mock factory
        mock_step = HttpRequestStep(
            {
                "method": "GET",
                "url": "http://api.example.com/data",
            },
            client_factory=mock_factory,
        )

        # Patch build_steps to return our mock step
        with patch("app.steps.registry.build_steps", return_value={"step1": mock_step}):
            submit_run_task.run(
                run_id=run.id,
                steps_data={
                    "step1": {
                        "type": "http_request",
                        "config": {
                            "method": "GET",
                            "url": "http://api.example.com/data",
                        },
                    }
                },
                definition=version.definition,
            )

        # Run should have been re-claimed and executed
        await db_session.refresh(run)
        assert run.status == "succeeded"
        assert run.claimed_at is not None  # Updated on re-claim

        await db_session.refresh(step_run)
        assert step_run.status == "succeeded"


class TestVersionCRUD:
    """Version CRUD operations within pipeline tests."""

    async def test_version_create_list(self, db_session: AsyncSession, test_user: User):
        """Test creating and listing versions."""
        pipeline = Pipeline(user_id=test_user.id, name="Version Test")
        db_session.add(pipeline)
        await db_session.flush()

        v1 = PipelineVersion(
            pipeline_id=pipeline.id,
            version_number=1,
            definition={"nodes": [{"id": "a"}]},
        )
        v2 = PipelineVersion(
            pipeline_id=pipeline.id,
            version_number=2,
            definition={"nodes": [{"id": "b"}]},
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
            select(Pipeline).where(
                Pipeline.id == pipeline.id, Pipeline.user_id == user_b.id
            )
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
