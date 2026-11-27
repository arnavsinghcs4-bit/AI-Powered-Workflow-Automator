"""Tests for Phase 4 stale-run recovery attempt cap marks a run failed."""
import pytest
from datetime import datetime, timezone, timedelta

from app.pipelines.models import Run, StepRun


class TestStaleRecoveryAttemptCap:
    """Test that recovery attempt cap marks a run as failed."""

    @pytest.mark.asyncio
    async def test_attempt_cap_marks_run_failed(self, db_session):
        """When recovery_attempts reaches the cap, the run is marked as failed."""
        from app.models import User

        # Create user
        user = User(email="cap-test@example.com", password_hash="$2b$12$test")
        db_session.add(user)
        await db_session.commit()

        # Create pipeline/version via raw SQL
        pipeline_id = (await db_session.execute(
            """INSERT INTO pipelines (user_id, name, description, is_active, created_at)
               VALUES (:uid, 'Cap Test', 'test', true, NOW()) RETURNING id""",
            {"uid": user.id}
        )).scalar_one()

        version_id = (await db_session.execute(
            """INSERT INTO pipeline_versions (pipeline_id, version_number, definition, created_at)
               VALUES (:pid, 1, '{}', NOW()) RETURNING id""",
            {"pid": pipeline_id}
        )).scalar_one()
        await db_session.commit()

        # Create run with high recovery_attempts (simulating capped recovery)
        run_id = (await db_session.execute(
            """INSERT INTO runs (pipeline_id, version_id, user_id, status, claimed_at, recovery_attempts, created_at)
               VALUES (:pid, :vid, :uid, 'running', :old, 5, NOW()) RETURNING id""",
            {"pid": pipeline_id, "vid": version_id, "uid": user.id, "old": datetime.now(timezone.utc) - timedelta(minutes=10)}
        )).scalar_one()
        await db_session.commit()

        # Run recovery - should succeed and set pending
        await db_session.execute(
            """UPDATE runs SET status='pending', claimed_at=NULL, recovery_attempts=6
               WHERE id=:rid AND status='running' AND claimed_at < (now() - interval '5 minutes')""",
            {"rid": run_id}
        )
        await db_session.commit()

        # Run should be failed due to recovery attempt cap
        run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        assert run.status == "failed"
        assert run.recovery_attempts >= 5  # Cap was reached