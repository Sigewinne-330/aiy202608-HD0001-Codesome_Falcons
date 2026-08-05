import sys
import unittest
from datetime import date, datetime, timezone
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
from models.schedule_personalization import (  # noqa: E402
    SchedulingConsentRevision,
    SchedulingDecisionEvent,
    SchedulingFeatureSnapshot,
    SchedulingGovernanceJob,
    SchedulingMemoryEntry,
    SchedulingWorkEvent,
    SchedulingWorkSession,
)
from services.schedule_personalization_governance import (  # noqa: E402
    advance_eligibility_watermark,
    get_or_create_private_consent,
    invalidate_memory_entry,
    personal_eligibility_query,
)


class PersonalizationGovernanceTests(unittest.TestCase):
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
            db.add(AppUser(username="governance", password="x", balance=10000))
            db.commit()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def _decision(self, watermark=1):
        return SchedulingDecisionEvent(
            decision_point_id=str(uuid4()),
            user_id=1,
            source_type="task",
            source_id=1,
            occurred_at=self._now(),
            local_date=date.today(),
            timezone="Asia/Shanghai",
            event_schema_version="event.v1",
            context_hash="a" * 64,
            candidate_snapshot=[],
            policy_version="policy.v1",
            eligible_personal=True,
            eligibility_watermark=watermark,
        )

    def test_private_consent_creation_is_versioned_and_idempotent(self):
        with self.SessionLocal() as db:
            first = get_or_create_private_consent(db, 1)
            second = get_or_create_private_consent(db, 1)
            db.commit()
            self.assertEqual(first.id, second.id)
            self.assertEqual(1, first.eligibility_watermark)
            self.assertFalse(first.operational_personalization_enabled)
            self.assertEqual(1, db.query(SchedulingConsentRevision).filter_by(user_id=1).count())

    def test_advancing_watermark_excludes_old_evidence_immediately(self):
        with self.SessionLocal() as db:
            get_or_create_private_consent(db, 1)
            db.add(self._decision())
            db.commit()
            self.assertEqual(1, personal_eligibility_query(db, SchedulingDecisionEvent, 1).count())

            result = advance_eligibility_watermark(
                db,
                1,
                reason="consent_withdrawn",
                idempotency_key="eligibility:1:withdrawal:1",
            )
            self.assertEqual(2, result.watermark)
            self.assertEqual(0, personal_eligibility_query(db, SchedulingDecisionEvent, 1).count())
            self.assertEqual(1, db.query(SchedulingDecisionEvent).count())
            self.assertEqual("pending", db.query(SchedulingGovernanceJob).one().status)
            db.commit()

    def test_repeated_governance_action_does_not_advance_twice(self):
        with self.SessionLocal() as db:
            get_or_create_private_consent(db, 1)
            first = advance_eligibility_watermark(
                db, 1, reason="model_reset", idempotency_key="eligibility:1:reset:1"
            )
            second = advance_eligibility_watermark(
                db, 1, reason="model_reset", idempotency_key="eligibility:1:reset:1"
            )
            self.assertFalse(first.repeated)
            self.assertTrue(second.repeated)
            self.assertEqual(first.watermark, second.watermark)
            self.assertEqual(first.job_id, second.job_id)
            self.assertEqual(1, db.query(SchedulingGovernanceJob).count())

    def test_raw_invalidation_discards_active_session_and_events(self):
        with self.SessionLocal() as db:
            get_or_create_private_consent(db, 1)
            session = SchedulingWorkSession(
                public_id=str(uuid4()),
                user_id=1,
                source_type="task",
                source_id=1,
                active_key="1:task:1",
                state="active",
                timezone="Asia/Shanghai",
                started_at=self._now(),
                current_interval_started_at=self._now(),
            )
            db.add(session)
            db.flush()
            event = SchedulingWorkEvent(
                event_id=str(uuid4()),
                user_id=1,
                session_id=session.id,
                source_type="task",
                source_id=1,
                event_type="started",
                idempotency_key="work-delete-1",
                effective_at=self._now(),
                effective_local_date=date.today(),
                timezone="Asia/Shanghai",
                provenance="active_timer",
                confidence="high",
                event_schema_version="event.v1",
                eligible_personal=True,
                eligibility_watermark=1,
            )
            db.add(event)
            db.commit()

            advance_eligibility_watermark(
                db,
                1,
                reason="account_delete",
                idempotency_key="eligibility:1:delete:1",
                invalidate_raw=True,
            )
            db.flush()
            self.assertIsNotNone(event.invalidated_at)
            self.assertFalse(event.eligible_personal)
            self.assertEqual("discarded", session.state)
            self.assertIsNone(session.active_key)

    def test_materialized_state_and_deleted_memory_are_excluded(self):
        with self.SessionLocal() as db:
            get_or_create_private_consent(db, 1)
            feature = SchedulingFeatureSnapshot(
                user_id=1,
                scope_type="user",
                scope_key="all",
                reference_date=date.today(),
                feature_schema_version="feature.v1",
                source_eligibility_watermark=1,
                effective_sample_size=1,
                sufficient_statistics={"n": 1},
            )
            memory = SchedulingMemoryEntry(
                memory_id=str(uuid4()),
                user_id=1,
                tier="llm_reflection",
                memory_key="writing",
                value_json={},
                display_text="Writing took longer.",
                source="llm",
                evidence_event_ids=[],
                schema_version="memory.v1",
                status="current",
                eligibility_watermark=1,
            )
            db.add_all([feature, memory])
            db.commit()
            self.assertEqual(1, personal_eligibility_query(db, SchedulingFeatureSnapshot, 1).count())
            self.assertEqual(1, personal_eligibility_query(db, SchedulingMemoryEntry, 1).count())

            deleted = invalidate_memory_entry(db, 1, memory.memory_id, suppression_fingerprint="f" * 64)
            self.assertEqual("deleted", deleted.status)
            self.assertEqual(0, personal_eligibility_query(db, SchedulingMemoryEntry, 1).count())

            advance_eligibility_watermark(
                db, 1, reason="consent_withdrawn", idempotency_key="eligibility:1:withdrawal:2"
            )
            self.assertEqual(0, personal_eligibility_query(db, SchedulingFeatureSnapshot, 1).count())
            self.assertIsNotNone(feature.invalidated_at)


if __name__ == "__main__":
    unittest.main()
