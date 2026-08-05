import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
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
    SchedulingConsentSetting,
    SchedulingDecisionEvent,
    SchedulingFeatureSnapshot,
    SchedulingGovernanceJob,
    SchedulingMemoryEntry,
    SchedulingModelPrediction,
    SchedulingModelRegistry,
    SchedulingOutcomeLabel,
    SchedulingWorkEvent,
    SchedulingWorkSession,
)


class PersonalizationModelTests(unittest.TestCase):
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
            db.add(AppUser(username="personal-model", password="x", balance=10000))
            db.commit()

    def test_all_personalization_tables_and_indexes_are_registered(self):
        inspector = inspect(self.engine)
        expected = {
            "scheduling_consent_settings",
            "scheduling_consent_revisions",
            "scheduling_decision_events",
            "scheduling_work_sessions",
            "scheduling_work_events",
            "scheduling_outcome_labels",
            "scheduling_memory_entries",
            "scheduling_feature_snapshots",
            "scheduling_model_registry",
            "scheduling_model_predictions",
            "scheduling_governance_jobs",
        }
        self.assertTrue(expected <= set(inspector.get_table_names()))
        for table_name in expected:
            self.assertTrue(inspector.get_indexes(table_name), table_name)

    def test_models_are_exported_from_authoritative_metadata(self):
        exported = {
            SchedulingConsentSetting,
            SchedulingConsentRevision,
            SchedulingDecisionEvent,
            SchedulingWorkSession,
            SchedulingWorkEvent,
            SchedulingOutcomeLabel,
            SchedulingMemoryEntry,
            SchedulingFeatureSnapshot,
            SchedulingModelRegistry,
            SchedulingModelPrediction,
            SchedulingGovernanceJob,
        }
        self.assertTrue(all(model.__table__ in Base.metadata.sorted_tables for model in exported))

    def test_consent_is_private_by_default_and_unique_per_user(self):
        with self.SessionLocal() as db:
            row = SchedulingConsentSetting(user_id=1, policy_version="consent.v1")
            db.add(row)
            db.commit()
            db.refresh(row)
            self.assertFalse(row.operational_personalization_enabled)
            self.assertFalse(row.cross_user_learning_enabled)
            self.assertEqual(365, row.raw_event_retention_days)
            db.add(SchedulingConsentSetting(user_id=1, policy_version="consent.v1"))
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_decision_and_work_event_idempotency_is_user_scoped(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.SessionLocal() as db:
            decision = SchedulingDecisionEvent(
                decision_point_id=str(uuid4()),
                user_id=1,
                source_type="task",
                source_id=1,
                idempotency_key="decision-key",
                occurred_at=now,
                local_date=date.today(),
                timezone="Asia/Shanghai",
                event_schema_version="event.v1",
                context_hash="a" * 64,
                candidate_snapshot=[],
                policy_version="policy.v1",
            )
            db.add(decision)
            db.commit()
            db.add(SchedulingDecisionEvent(
                decision_point_id=str(uuid4()),
                user_id=1,
                source_type="task",
                source_id=1,
                idempotency_key="decision-key",
                occurred_at=now,
                local_date=date.today(),
                timezone="Asia/Shanghai",
                event_schema_version="event.v1",
                context_hash="b" * 64,
                candidate_snapshot=[],
                policy_version="policy.v1",
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            common = dict(
                user_id=1,
                source_type="task",
                source_id=1,
                event_type="started",
                effective_at=now,
                effective_local_date=date.today(),
                timezone="Asia/Shanghai",
                provenance="direct_user",
                confidence="high",
                event_schema_version="event.v1",
            )
            db.add(SchedulingWorkEvent(event_id=str(uuid4()), idempotency_key="work-key", **common))
            db.commit()
            db.add(SchedulingWorkEvent(event_id=str(uuid4()), idempotency_key="work-key", **common))
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_active_session_key_prevents_two_open_sessions_for_source(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.SessionLocal() as db:
            common = dict(
                user_id=1,
                source_type="task",
                source_id=1,
                active_key="1:task:1",
                state="active",
                timezone="Asia/Shanghai",
                started_at=now,
                current_interval_started_at=now,
            )
            db.add(SchedulingWorkSession(public_id=str(uuid4()), **common))
            db.commit()
            db.add(SchedulingWorkSession(public_id=str(uuid4()), **common))
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_invalid_lifecycle_and_probability_fail_database_checks(self):
        with self.SessionLocal() as db:
            db.add(SchedulingModelRegistry(
                model_id=str(uuid4()),
                user_id=1,
                model_type="effort",
                scope="personal",
                lifecycle="executable",
                algorithm_version="v1",
                feature_schema_version="v1",
                artifact_json={"mean": 1},
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            db.add(SchedulingModelPrediction(
                prediction_id=str(uuid4()),
                user_id=1,
                context_hash="a" * 64,
                prediction_type="completion_risk",
                probability=1.5,
                serving_mode="shadow",
            ))
            with self.assertRaises(IntegrityError):
                db.commit()


if __name__ == "__main__":
    unittest.main()
