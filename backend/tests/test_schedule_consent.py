import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import (  # noqa: E402
    SchedulingConsentRevision,
    SchedulingDecisionEvent,
    SchedulingGovernanceJob,
    SchedulingWorkSession,
)
from models.task_new import Task  # noqa: E402
from schemas.schedule_personalization import ConsentSettingsUpdate  # noqa: E402
from services.schedule_consent import ConsentVersionConflict, update_consent_settings  # noqa: E402
from services.schedule_personalization_governance import (  # noqa: E402
    get_or_create_private_consent,
    personal_eligibility_query,
)


class ScheduleConsentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.SessionLocal() as db:
            db.add(AppUser(username="consent-user", password="x", balance=10000))
            db.flush()
            db.add(Task(user_id=1, title="consent source"))
            db.commit()

    @staticmethod
    def _enabled_update(**changes):
        values = {
            "operational_personalization_enabled": True,
            "work_session_capture_enabled": True,
            "llm_memory_enabled": False,
            "cross_user_learning_enabled": False,
            "near_tie_exploration_enabled": False,
            "raw_event_retention_days": 365,
            "rebuild_after_reset_enabled": False,
        }
        values.update(changes)
        return ConsentSettingsUpdate(**values)

    def test_private_default_and_versioned_update_are_idempotent(self):
        with self.SessionLocal() as db:
            private = get_or_create_private_consent(db, 1)
            self.assertFalse(private.operational_personalization_enabled)
            updated = update_consent_settings(db, 1, self._enabled_update(expected_version=1))
            self.assertEqual(2, updated.version)
            self.assertTrue(updated.work_session_capture_enabled)
            replay = update_consent_settings(db, 1, self._enabled_update(expected_version=2))
            self.assertEqual(2, replay.version)
            self.assertEqual(2, db.query(SchedulingConsentRevision).count())
            with self.assertRaises(ConsentVersionConflict):
                update_consent_settings(db, 1, self._enabled_update(expected_version=1))

    def test_operational_withdrawal_excludes_old_evidence_and_discards_open_timer(self):
        with self.SessionLocal() as db:
            update_consent_settings(db, 1, self._enabled_update())
            consent = get_or_create_private_consent(db, 1)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(SchedulingDecisionEvent(
                decision_point_id="11111111-1111-1111-1111-111111111111",
                user_id=1,
                source_type="task",
                source_id=1,
                occurred_at=now,
                local_date=date.today(),
                timezone="Asia/Shanghai",
                event_schema_version="event.v1",
                context_hash="a" * 64,
                candidate_snapshot=[],
                policy_version="policy.v1",
                eligible_personal=True,
                eligibility_watermark=consent.eligibility_watermark,
            ))
            db.add(SchedulingWorkSession(
                public_id="22222222-2222-2222-2222-222222222222",
                user_id=1,
                source_type="task",
                source_id=1,
                active_key="1:task:1",
                state="active",
                timezone="Asia/Shanghai",
                started_at=now,
                current_interval_started_at=now,
            ))
            db.flush()
            self.assertEqual(1, personal_eligibility_query(db, SchedulingDecisionEvent, 1).count())
            withdrawn = update_consent_settings(db, 1, ConsentSettingsUpdate(expected_version=2))
            self.assertEqual(3, withdrawn.version)
            self.assertEqual(2, withdrawn.eligibility_watermark)
            self.assertEqual(0, personal_eligibility_query(db, SchedulingDecisionEvent, 1).count())
            self.assertEqual("discarded", db.query(SchedulingWorkSession).one().state)
            self.assertTrue(db.query(SchedulingGovernanceJob).filter_by(job_type="propagate_deletion").count())

    def test_cross_user_withdrawal_stops_contribution_without_invalidating_personal_evidence(self):
        with self.SessionLocal() as db:
            update_consent_settings(db, 1, self._enabled_update(cross_user_learning_enabled=True))
            consent = get_or_create_private_consent(db, 1)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            event = SchedulingDecisionEvent(
                decision_point_id="33333333-3333-3333-3333-333333333333",
                user_id=1,
                source_type="task",
                source_id=1,
                occurred_at=now,
                local_date=date.today(),
                timezone="Asia/Shanghai",
                event_schema_version="event.v1",
                context_hash="b" * 64,
                candidate_snapshot=[],
                policy_version="policy.v1",
                eligible_personal=True,
                eligible_cross_user=True,
                eligibility_watermark=consent.eligibility_watermark,
            )
            db.add(event)
            db.flush()
            updated = update_consent_settings(db, 1, self._enabled_update(
                expected_version=2,
                cross_user_learning_enabled=False,
            ))
            db.refresh(event)
            self.assertEqual(1, updated.eligibility_watermark)
            self.assertTrue(event.eligible_personal)
            self.assertFalse(event.eligible_cross_user)
            self.assertTrue(db.query(SchedulingGovernanceJob).filter_by(job_type="recompute_aggregate").count())


if __name__ == "__main__":
    unittest.main()
