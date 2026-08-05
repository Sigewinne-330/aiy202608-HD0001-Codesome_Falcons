import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import SchedulingGovernanceJob, SchedulingModelRegistry  # noqa: E402
from services.schedule_personalization_governance import enqueue_governance_job, get_or_create_private_consent  # noqa: E402
from services.schedule_personalization_jobs import (  # noqa: E402
    claim_governance_jobs,
    execute_claimed_job,
)


class SchedulePersonalizationJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.SessionLocal() as db:
            db.add(AppUser(username="job-user", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            db.commit()

    def _job(self, db, key="job-one", job_type="refresh_features", not_before=None):
        job = enqueue_governance_job(
            db,
            idempotency_key=key,
            job_type=job_type,
            user_id=1,
            payload={"eligibility_watermark": 1},
        )
        if not_before is not None:
            job.not_before = not_before
            db.flush()
        return job

    def test_claim_is_idempotent_across_workers_and_expired_lease_recovers(self):
        now = datetime(2026, 8, 5, 12, 0, 0)
        with self.SessionLocal() as db:
            self._job(db, not_before=now)
            first = claim_governance_jobs(db, worker_id="worker-a", now=now, lease_seconds=30)
            second = claim_governance_jobs(db, worker_id="worker-b", now=now, lease_seconds=30)
            self.assertEqual(1, len(first))
            self.assertEqual(0, len(second))
            db.commit()
        with self.SessionLocal() as db:
            reclaimed = claim_governance_jobs(
                db, worker_id="worker-b", now=now + timedelta(seconds=31), lease_seconds=30
            )
            self.assertEqual(1, len(reclaimed))
            self.assertEqual(2, reclaimed[0].attempt)

    def test_partial_failure_rolls_back_and_retries_then_becomes_terminal(self):
        now = datetime(2026, 8, 5, 12, 0, 0)
        with self.SessionLocal() as db:
            self._job(db, not_before=now)
            claim = claim_governance_jobs(db, worker_id="worker-a", now=now)[0]

            def partial_failure(session, _job):
                session.add(SchedulingModelRegistry(
                    model_id=str(uuid4()), user_id=1, model_type="effort", scope="personal",
                    lifecycle="candidate", algorithm_version="bad", feature_schema_version="bad",
                    source_eligibility_watermark=1, effective_sample_size=0,
                    artifact_json={"kind": "temporary"}, evaluation_metrics={}, slice_metrics={},
                ))
                session.flush()
                raise RuntimeError("injected partial failure")

            first = execute_claimed_job(
                db, claim, handlers={"refresh_features": partial_failure}, now=now,
                maximum_attempts=2, retry_delay_seconds=1,
            )
            self.assertTrue(first.retry_scheduled)
            self.assertEqual(0, db.query(SchedulingModelRegistry).count())
            db.commit()
        with self.SessionLocal() as db:
            claim = claim_governance_jobs(
                db, worker_id="worker-b", now=now + timedelta(seconds=2)
            )[0]
            final = execute_claimed_job(
                db, claim, handlers={"refresh_features": partial_failure}, now=now + timedelta(seconds=2),
                maximum_attempts=2,
            )
            self.assertEqual("failed", final.status)
            self.assertFalse(final.retry_scheduled)
            self.assertEqual(0, db.query(SchedulingModelRegistry).count())

    def test_update_handler_cannot_self_promote_and_previous_model_survives(self):
        now = datetime(2026, 8, 5, 12, 0, 0)
        with self.SessionLocal() as db:
            previous = SchedulingModelRegistry(
                model_id=str(uuid4()), user_id=1, model_type="effort", scope="personal",
                lifecycle="promoted", algorithm_version="v1", feature_schema_version="f1",
                source_eligibility_watermark=1, effective_sample_size=10,
                artifact_json={"kind": "prior"}, evaluation_metrics={}, slice_metrics={},
            )
            db.add(previous)
            self._job(db, key="model-update", job_type="update_model", not_before=now)
            db.flush()
            claim = claim_governance_jobs(db, worker_id="worker-a", now=now)[0]

            def forbidden_promotion(session, _job):
                candidate = SchedulingModelRegistry(
                    model_id=str(uuid4()), user_id=1, model_type="effort", scope="personal",
                    lifecycle="promoted", algorithm_version="v2", feature_schema_version="f1",
                    source_eligibility_watermark=1, effective_sample_size=20,
                    artifact_json={"kind": "unsafe"}, evaluation_metrics={}, slice_metrics={},
                )
                session.add(candidate)
                session.flush()
                return {"model_id": candidate.model_id}

            result = execute_claimed_job(
                db, claim, handlers={"update_model": forbidden_promotion}, now=now
            )
            self.assertEqual("pending", result.status)
            self.assertEqual([previous.model_id], [row.model_id for row in db.query(
                SchedulingModelRegistry
            ).filter_by(lifecycle="promoted").all()])

    def test_watermark_change_during_job_fails_closed(self):
        now = datetime(2026, 8, 5, 12, 0, 0)
        with self.SessionLocal() as db:
            self._job(db, not_before=now)
            claim = claim_governance_jobs(db, worker_id="worker-a", now=now)[0]
            consent = get_or_create_private_consent(db, 1)
            consent.eligibility_watermark = 2

            def check_consent(session, job):
                from services.schedule_personalization_jobs import DEFAULT_JOB_HANDLERS
                return DEFAULT_JOB_HANDLERS[job.job_type](session, job)

            result = execute_claimed_job(
                db, claim, handlers={"refresh_features": check_consent}, now=now
            )
            self.assertEqual("pending", result.status)
            self.assertEqual("GovernanceJobError", result.error_code)


if __name__ == "__main__":
    unittest.main()
