import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

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
    SchedulingFeatureSnapshot,
    SchedulingGovernanceJob,
    SchedulingMemoryEntry,
    SchedulingModelPrediction,
    SchedulingModelRegistry,
    SchedulingWorkEvent,
)
from models.task_new import Task  # noqa: E402
from schemas.schedule_personalization import (  # noqa: E402
    MemoryEntryInput,
    PersonalizationResetRequest,
    WorkEventInput,
)
from services.schedule_data_controls import (  # noqa: E402
    deletion_status,
    portable_personalization_export,
    prepare_personalization_account_deletion,
    reset_personalization_model,
)
from services.schedule_memory import create_memory_entry, delete_owned_memory  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_work_events import apply_work_event  # noqa: E402


class ScheduleDataControlTests(unittest.TestCase):
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
            db.add_all([
                AppUser(username="controls-one", password="x", balance=10000),
                AppUser(username="controls-two", password="x", balance=10000),
            ])
            db.flush()
            db.add_all([Task(user_id=1, title="control source"), Task(user_id=2, title="foreign")])
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            consent.llm_memory_enabled = True
            db.commit()

    def _raw_event(self, db):
        now = datetime.now(timezone.utc)
        return apply_work_event(db, 1, WorkEventInput(
            event_type="progressed",
            source={"source_type": "task", "source_id": 1},
            idempotency_key="control-evidence-1",
            effective_at=now,
            progress_ratio=0.5,
        ), server_now=now).event

    def _derived_state(self, db, evidence_id):
        explicit = create_memory_entry(db, 1, MemoryEntryInput(
            tier="explicit_declaration",
            memory_key="explicit_rule",
            value_json={"minutes": 45},
            display_text="Use 45 minute blocks.",
        ), source="user")
        reflection = create_memory_entry(db, 1, MemoryEntryInput(
            tier="llm_reflection",
            memory_key="reflection_rule",
            value_json={"multiplier": 1.2},
            display_text="Work may take longer.",
            evidence_event_ids=[UUID(evidence_id)],
            confidence=0.7,
        ), source="llm", generated_by_model="mock", prompt_version="v1")
        feature = SchedulingFeatureSnapshot(
            user_id=1,
            scope_type="user",
            scope_key="all",
            reference_date=date.today(),
            feature_schema_version="scheduling-feature.v1",
            source_eligibility_watermark=1,
            effective_sample_size=1,
            sufficient_statistics={"n": 1},
        )
        model = SchedulingModelRegistry(
            model_id=str(uuid4()),
            user_id=1,
            model_type="effort",
            scope="personal",
            lifecycle="promoted",
            algorithm_version="empirical-bayes.v1",
            feature_schema_version="scheduling-feature.v1",
            source_eligibility_watermark=1,
            effective_sample_size=1,
            artifact_json={"prior": 1},
        )
        db.add_all([feature, model])
        db.flush()
        prediction = SchedulingModelPrediction(
            prediction_id=str(uuid4()),
            user_id=1,
            model_registry_id=model.id,
            context_hash="a" * 64,
            prediction_type="effort",
            p50=2,
            evidence_maturity=0.5,
            feature_contributions={},
            serving_mode="shadow",
            latency_ms=1,
            eligibility_watermark=1,
        )
        db.add(prediction)
        db.flush()
        return explicit, reflection, feature, model, prediction

    def test_model_reset_immediately_invalidates_derived_state_but_preserves_raw_and_explicit(self):
        with self.SessionLocal() as db:
            raw = self._raw_event(db)
            explicit, reflection, feature, model, prediction = self._derived_state(db, raw.event_id)
            job = reset_personalization_model(db, 1, PersonalizationResetRequest(
                idempotency_key="reset-control-01",
                rebuild_from_retained_evidence=True,
                expected_settings_version=1,
            ))
            replay = reset_personalization_model(db, 1, PersonalizationResetRequest(
                idempotency_key="reset-control-01",
                rebuild_from_retained_evidence=True,
                expected_settings_version=1,
            ))
            db.refresh(raw)
            db.refresh(explicit)
            db.refresh(reflection)
            db.refresh(feature)
            db.refresh(model)
            db.refresh(prediction)
            self.assertEqual(job.id, replay.id)
            self.assertIsNone(raw.invalidated_at)
            self.assertIsNone(explicit.invalidated_at)
            self.assertIsNotNone(reflection.invalidated_at)
            self.assertIsNotNone(feature.invalidated_at)
            self.assertIsNotNone(model.invalidated_at)
            self.assertIsNotNone(prediction.invalidated_at)
            self.assertEqual(1, raw.eligibility_watermark)
            self.assertTrue(db.query(SchedulingGovernanceJob).filter_by(job_type="refresh_features").count())

    def test_export_is_owner_scoped_portable_and_omits_deleted_memory_content(self):
        with self.SessionLocal() as db:
            raw = self._raw_event(db)
            explicit, reflection, *_ = self._derived_state(db, raw.event_id)
            deleted_text = reflection.display_text
            delete_owned_memory(db, 1, reflection.memory_id)
            export = portable_personalization_export(db, 1)
            self.assertEqual("scheduling-personalization-export.v1", export["schema_version"])
            serialized = str(export)
            self.assertNotIn(deleted_text, serialized)
            self.assertIn(reflection.memory_id, [row["memory_id"] for row in export["deleted_memory_tombstones"]])
            self.assertIn(explicit.memory_id, [row["memory_id"] for row in export["memories"]])
            self.assertNotIn("controls-two", serialized)
            self.assertNotIn("idempotency_key", serialized)

    def test_memory_delete_and_account_delete_status_are_idempotent_and_immediately_ineligible(self):
        with self.SessionLocal() as db:
            raw = self._raw_event(db)
            explicit = create_memory_entry(db, 1, MemoryEntryInput(
                tier="explicit_declaration",
                memory_key="delete_me",
                value_json={"minutes": 30},
                display_text="Delete this.",
            ), source="user")
            delete_owned_memory(db, 1, explicit.memory_id)
            delete_owned_memory(db, 1, explicit.memory_id)
            self.assertEqual(1, db.query(SchedulingGovernanceJob).filter(
                SchedulingGovernanceJob.idempotency_key.like("memory-delete:%")
            ).count())
            first = prepare_personalization_account_deletion(
                db, 1, idempotency_key="account-control-1"
            )
            second = prepare_personalization_account_deletion(
                db, 1, idempotency_key="account-control-1"
            )
            db.refresh(raw)
            self.assertEqual(first.id, second.id)
            self.assertIsNotNone(raw.invalidated_at)
            self.assertFalse(raw.eligible_personal)
            status = deletion_status(db, 1)
            self.assertEqual("pending", status["state"])
            self.assertTrue(status["operations"])
            self.assertNotIn("job_id", str(status))


if __name__ == "__main__":
    unittest.main()
