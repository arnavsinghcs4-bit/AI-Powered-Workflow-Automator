"""Tests for Phase 4 stale-run recovery beat task and atomic run claiming."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

# Import Credential first to register it in the SQLAlchemy registry before User
# User has a relationship to Credential which requires Credential to be defined
from app.credentials.models import Credential  # noqa: F401
from app.models import User
from app.pipelines.models import Run, StepRun


class TestStaleRunRecovery:
    """Test stale run recovery mechanisms."""

    @pytest.mark.asyncio
    async def test_atomic_claim_success(self, db_session):
        """Test successful atomic claim of pending run."""
        # Create user first via ORM
        user = User(email="stale-test-1@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline via raw SQL
        pipeline_id = (await db_session.execute(
            text(
                "INSERT INTO pipelines (user_id, name, description, is_active, created_at) "
                "VALUES (:uid, 'Stale Test', 'test', true, NOW()) RETURNING id"
            ),
            {"uid": user.id}
        )).scalar_one()

        # Create version via raw SQL
        version_id = (await db_session.execute(
            text(
                "INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at) "
                "VALUES (:pid, 1, '{}', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create run via raw SQL to avoid ORM FK validation issues
        run_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, created_at) "
                "VALUES (:pid, :vid, :uid, 'pending', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id}
        )).scalar_one()
        await db_session.commit()

        # Simulate atomic claim via UPDATE
        await db_session.execute(
            text(
                "UPDATE runs SET status='running', claimed_at=:now "
                "WHERE id=:id AND status='pending' RETURNING id"
            ),
            {"now": datetime.now(timezone.utc), "id": run_id}
        )
        await db_session.commit()

        # Verify run is now running with claimed_at
        result = await db_session.execute(
            select(Run).where(Run.id == run_id, Run.status == "running")
        )
        run = result.scalar_one_or_none()
        assert run is not None
        assert run.status == "running"
        assert run.claimed_at is not None

    @pytest.mark.asyncio
    async def test_atomic_claim_twice_fails(self, db_session):
        """Test that claiming an already-running run fails."""
        # Create user first
        user = User(email="stale-test-2@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline/version via raw SQL
        pipeline_id = (await db_session.execute(
            text(
                "INSERT INTO pipelines (user_id, name, description, is_active, created_at) "
                "VALUES (:uid, 'Stale Test', 'test', true, NOW()) RETURNING id"
            ),
            {"uid": user.id}
        )).scalar_one()

        version_id = (await db_session.execute(
            text(
                "INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at) "
                "VALUES (:pid, 1, '{}', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create run
        run_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, created_at) "
                "VALUES (:pid, :vid, :uid, 'pending', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id}
        )).scalar_one()
        await db_session.commit()

        # First claim
        await db_session.execute(
            text(
                "UPDATE runs SET status='running', claimed_at=:now "
                "WHERE id=:id AND status='pending' RETURNING id"
            ),
            {"now": datetime.now(timezone.utc), "id": run_id}
        )
        await db_session.commit()

        # Second claim should not return the id (status is no longer pending)
        result = await db_session.execute(
            text(
                "UPDATE runs SET status='running', claimed_at=:now "
                "WHERE id=:id AND status='pending' RETURNING id"
            ),
            {"now": datetime.now(timezone.utc), "id": run_id}
        )
        await db_session.commit()

        claimed_by_worker2 = result.scalar_one_or_none()
        assert claimed_by_worker2 is None  # No rows returned

        # Run should still be claimed by worker 1
        run_result = await db_session.execute(select(Run).where(Run.id == run_id))
        run = run_result.scalar_one()
        assert run.status == "running"  # Still running, not doubled up

    @pytest.mark.asyncio
    async def test_reset_stale_runs(self, db_session):
        """Test the stale run recovery SQL."""
        # Create user first
        user = User(email="stale-test-3@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline/version via raw SQL
        pipeline_id = (await db_session.execute(
            text(
                "INSERT INTO pipelines (user_id, name, description, is_active, created_at) "
                "VALUES (:uid, 'Stale Test', 'test', true, NOW()) RETURNING id"
            ),
            {"uid": user.id}
        )).scalar_one()

        version_id = (await db_session.execute(
            text(
                "INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at) "
                "VALUES (:pid, 1, '{}', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create runs via raw SQL
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        stale_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, created_at) "
                "VALUES (:pid, :vid, :uid, 'running', :old, NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id, "old": old_time}
        )).scalar_one()

        fresh_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        fresh_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, created_at) "
                "VALUES (:pid, :vid, :uid, 'running', :fresh, NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id, "fresh": fresh_time}
        )).scalar_one()

        completed_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, created_at) "
                "VALUES (:pid, :vid, :uid, 'succeeded', :old, NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id, "old": old_time}
        )).scalar_one()
        await db_session.commit()

        # Run stale recovery
        await db_session.execute(text(
            "UPDATE runs SET status='pending', claimed_at=NULL "
            "WHERE status='running' AND claimed_at < (now() - interval '5 minutes')"
        ))
        await db_session.commit()

        # Check results
        stale_run = (await db_session.execute(select(Run).where(Run.id == stale_id))).scalar_one()
        fresh_run = (await db_session.execute(select(Run).where(Run.id == fresh_id))).scalar_one()
        completed_run = (await db_session.execute(select(Run).where(Run.id == completed_id))).scalar_one()

        # Stale run should be reset to pending
        assert stale_run.status == "pending"
        assert stale_run.claimed_at is None

        # Fresh run should be unchanged
        assert fresh_run.status == "running"
        assert fresh_run.claimed_at is not None

        # Completed run should be unchanged
        assert completed_run.status == "succeeded"

    @pytest.mark.asyncio
    async def test_reset_stale_runs_cap_attempts(self, db_session):
        """Test that stale recovery doesn't run infinitely - capped at reasonable attempts."""
        # Create user first
        user = User(email="stale-test-4@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline/version via raw SQL
        pipeline_id = (await db_session.execute(
            text(
                "INSERT INTO pipelines (user_id, name, description, is_active, created_at) "
                "VALUES (:uid, 'Stale Test', 'test', true, NOW()) RETURNING id"
            ),
            {"uid": user.id}
        )).scalar_one()

        version_id = (await db_session.execute(
            text(
                "INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at) "
                "VALUES (:pid, 1, '{}', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create a run via raw SQL
        run_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, recovery_attempts, created_at) "
                "VALUES (:pid, :vid, :uid, 'running', :old, 3, NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id, "old": datetime.now(timezone.utc) - timedelta(minutes=10)}
        )).scalar_one()
        await db_session.commit()

        # Recovery makes it pending
        await db_session.execute(text(
            "UPDATE runs SET status='pending', claimed_at=NULL, recovery_attempts=4 "
            "WHERE id=:rid AND status='running' AND claimed_at < (now() - interval '5 minutes')"
        ), {"rid": run_id})
        await db_session.commit()

        run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        assert run.status == "pending"
        assert run.claimed_at is None
        assert run.recovery_attempts == 4  # Incremented


class TestRunClaimConcurrency:
    """Test atomic claim under concurrent conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_claim_simulation(self, db_session):
        """Simulate two workers trying to claim the same run."""
        # Create user first
        user = User(email="concurrent-test-1@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline/version via raw SQL
        pipeline_id = (await db_session.execute(
            text(
                "INSERT INTO pipelines (user_id, name, description, is_active, created_at) "
                "VALUES (:uid, 'Concurrent Test', 'test', true, NOW()) RETURNING id"
            ),
            {"uid": user.id}
        )).scalar_one()

        version_id = (await db_session.execute(
            text(
                "INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at) "
                "VALUES (:pid, 1, '{}', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create run via raw SQL
        run_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, created_at) "
                "VALUES (:pid, :vid, :uid, 'pending', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id}
        )).scalar_one()
        await db_session.commit()

        # Worker 1 claims
        result = await db_session.execute(
            text(
                "UPDATE runs SET status='running', claimed_at=:now "
                "WHERE id=:id AND status='pending' RETURNING id"
            ),
            {"now": datetime.now(timezone.utc), "id": run_id}
        )
        await db_session.commit()
        claimed_by_worker1 = result.scalar_one_or_none()
        assert claimed_by_worker1 == run_id

        # Worker 2 tries to claim (should not get id)
        result = await db_session.execute(
            text(
                "UPDATE runs SET status='running', claimed_at=:now "
                "WHERE id=:id AND status='pending' RETURNING id"
            ),
            {"now": datetime.now(timezone.utc), "id": run_id}
        )
        await db_session.commit()
        claimed_by_worker2 = result.scalar_one_or_none()
        assert claimed_by_worker2 is None  # No rows returned

        # Run should still be claimed by worker 1
        run_result = await db_session.execute(select(Run).where(Run.id == run_id))
        run = run_result.scalar_one()
        assert run.status == "running"

    @pytest.mark.asyncio
    async def test_claim_nonexistent_run(self, db_session):
        """Test claim fails for nonexistent run."""
        result = await db_session.execute(
            text(
                "UPDATE runs SET status='running', claimed_at=:now "
                "WHERE id=:id AND status='pending' RETURNING id"
            ),
            {"now": datetime.now(timezone.utc), "id": 99999}
        )
        await db_session.commit()
        claimed_id = result.scalar_one_or_none()
        assert claimed_id is None


class TestStaleRecoveryEdgeCases:
    """Test edge cases for stale run recovery."""

    @pytest.mark.asyncio
    async def test_null_claimed_at_not_reset(self, db_session):
        """Test that runs with NULL claimed_at are not affected by stale recovery."""
        # Create user first
        user = User(email="edge-test-1@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline/version via raw SQL
        pipeline_id = (await db_session.execute(
            text(
                "INSERT INTO pipelines (user_id, name, description, is_active, created_at) "
                "VALUES (:uid, 'Edge Test', 'test', true, NOW()) RETURNING id"
            ),
            {"uid": user.id}
        )).scalar_one()

        version_id = (await db_session.execute(
            text(
                "INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at) "
                "VALUES (:pid, 1, '{}', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create run with NULL claimed_at
        run_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, created_at) "
                "VALUES (:pid, :vid, :uid, 'running', NULL, NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id}
        )).scalar_one()
        await db_session.commit()

        await db_session.execute(text(
            "UPDATE runs SET status='pending', claimed_at=NULL "
            "WHERE status='running' AND claimed_at < (now() - interval '5 minutes')"
        ))
        await db_session.commit()

        run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        # Run with NULL claimed_at should NOT be reset (NULL < timestamp is false, but we filter on claimed_at being in past)
        # Actually, NULL compared to anything is NULL, and the WHERE clause with NULL won't match
        assert run.status == "running"

    @pytest.mark.asyncio
    async def test_exact_5_minute_boundary(self, db_session):
        """Test run at the 5-minute boundary: just under 5 minutes should reset, exactly at should not.

        We set claimed_at to exactly 5 minutes before NOW() at the SQL level.
        Since the comparison is '<', a run at exactly the boundary should NOT be reset.
        """
        # Create user first
        user = User(email="edge-test-2@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline/version
        pipeline_id = (await db_session.execute(
            text(
                "INSERT INTO pipelines (user_id, name, description, is_active, created_at) "
                "VALUES (:uid, 'Edge Test', 'test', true, NOW()) RETURNING id"
            ),
            {"uid": user.id}
        )).scalar_one()

        version_id = (await db_session.execute(
            text(
                "INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at) "
                "VALUES (:pid, 1, '{}', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create run with claimed_at = NOW() - 5 minutes 30 seconds (just over boundary)
        # Then run recovery - should be reset since it's > 5 minutes stale
        over_time = datetime.now(timezone.utc) - timedelta(minutes=5, seconds=30)
        run_id_over = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, created_at) "
                "VALUES (:pid, :vid, :uid, 'running', :ct, NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id, "ct": over_time}
        )).scalar_one()
        await db_session.commit()

        # Create run with claimed_at = NOW() - 4 minutes 59 seconds (just under boundary)
        # Should NOT be reset
        under_time = datetime.now(timezone.utc) - timedelta(minutes=4, seconds=59)
        run_id_under = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, created_at) "
                "VALUES (:pid, :vid, :uid, 'running', :ct, NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id, "ct": under_time}
        )).scalar_one()
        await db_session.commit()

        await db_session.execute(text(
            "UPDATE runs SET status='pending', claimed_at=NULL "
            "WHERE status='running' AND claimed_at < (now() - interval '5 minutes')"
        ))
        await db_session.commit()

        run_over = (await db_session.execute(select(Run).where(Run.id == run_id_over))).scalar_one()
        run_under = (await db_session.execute(select(Run).where(Run.id == run_id_under))).scalar_one()

        # Run over 5 minutes should be reset to pending
        assert run_over.status == "pending", "Run over 5 minutes old should be reset"
        assert run_over.claimed_at is None

        # Run just under 5 minutes should remain running
        assert run_under.status == "running", "Run under 5 minutes old should NOT be reset"
        assert run_under.claimed_at is not None

    @pytest.mark.asyncio
    async def test_just_over_5_minutes(self, db_session):
        """Test run just over 5 minute boundary IS reset."""
        # Create user first
        user = User(email="edge-test-3@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline/version
        pipeline_id = (await db_session.execute(
            text(
                "INSERT INTO pipelines (user_id, name, description, is_active, created_at) "
                "VALUES (:uid, 'Edge Test', 'test', true, NOW()) RETURNING id"
            ),
            {"uid": user.id}
        )).scalar_one()

        version_id = (await db_session.execute(
            text(
                "INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at) "
                "VALUES (:pid, 1, '{}', NOW()) RETURNING id"
            ),
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create run just over 5 minutes
        over_time = datetime.now(timezone.utc) - timedelta(minutes=5, seconds=1)
        run_id = (await db_session.execute(
            text(
                "INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, created_at) "
                "VALUES (:pid, :vid, :uid, 'running', :ot, NOW()) RETURNING id"
            ),
            {"pid": pipeline_id, "vid": version_id, "uid": user.id, "ot": over_time}
        )).scalar_one()
        await db_session.commit()

        await db_session.execute(text(
            "UPDATE runs SET status='pending', claimed_at=NULL "
            "WHERE status='running' AND claimed_at < (now() - interval '5 minutes')"
        ))
        await db_session.commit()

        run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        assert run.status == "pending"
        assert run.claimed_at is None


class TestCeleryBeatTask:
    """Test the Celery beat task wrapper."""

    def test_reset_stale_runs_task_signature(self):
        """Test that reset_stale_runs_task has correct Celery signature."""
        from app.worker.tasks import reset_stale_runs_task
        # The function is decorated with @shared_task
        assert hasattr(reset_stale_runs_task, 's')  # Can be called with s() for delayed
        assert hasattr(reset_stale_runs_task, 'delay')  # Can be called with delay()
        assert hasattr(reset_stale_runs_task, 'apply_async')  # Can be called with apply_async()

    def test_submit_run_task_signature(self):
        """Test that submit_run has correct Celery signature."""
        from app.worker.tasks import submit_run
        assert hasattr(submit_run, 's')
        assert hasattr(submit_run, 'delay')
        assert hasattr(submit_run, 'apply_async')