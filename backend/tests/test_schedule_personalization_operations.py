import sys
import unittest
from datetime import date
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
from services.schedule_adaptive_ranking import SafeCandidateSnapshot  # noqa: E402
from services.schedule_model_registry import (  # noqa: E402
    RegistryCompatibility, move_to_shadow, promote_model, register_candidate
)
from services.schedule_personalization_config import PersonalizationRuntimeConfig  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_personalization_operations import (  # noqa: E402
    global_kill_active,
    kill_model_with_incident,
    personalization_readiness,
    serving_version_history,
    set_global_kill,
)
from services.schedule_personalization_serving import serve_personalization  # noqa: E402


class SchedulePersonalizationOperationsTests(unittest.TestCase):
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
            db.add(AppUser(username="operations-user", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            db.commit()
        self.compatibility = RegistryCompatibility("v1", "f1", "l1", "c1")

    def _promoted(self, db, value):
        row = register_candidate(
            db, user_id=1, model_type="reranker", scope="personal",
            algorithm_version="v1", feature_schema_version="f1", label_version="l1",
            calibration_version="c1", artifact_json={"kind": "linear", "value": value},
        )
        move_to_shadow(db, row.model_id)
        promote_model(db, row.model_id, approved_by="test", compatibility=self.compatibility)
        return row

    def test_global_kill_is_idempotent_audited_and_immediately_restores_baseline(self):
        config = PersonalizationRuntimeConfig(master_enabled=True, modeling_enabled=True, shadow_enabled=True)
        candidate = SafeCandidateSnapshot(
            "date:2026-08-10", date(2026, 8, 10), 1, 1, ("safe",), ("hard",), 60,
        )
        with self.SessionLocal() as db:
            model = self._promoted(db, 1)
            first = set_global_kill(
                db, active=True, reason="incident", actor="admin:1", idempotency_key="global-kill-001"
            )
            repeated = set_global_kill(
                db, active=True, reason="incident", actor="admin:1", idempotency_key="global-kill-001"
            )
            self.assertFalse(first.repeated)
            self.assertTrue(repeated.repeated)
            self.assertTrue(global_kill_active(db))
            result = serve_personalization(
                db, user_id=1, candidates=(candidate,), predictor=lambda _items: (), model=model,
                context_identity="incident", config=config,
            )
            self.assertEqual("killed", result.mode.value)
            self.assertEqual(result.ranking.baseline_order, result.ranking.display_order)
            self.assertEqual("global_kill_switch", result.fallback_reason)

            set_global_kill(
                db, active=False, reason="recovered", actor="admin:1", idempotency_key="global-kill-002"
            )
            self.assertFalse(global_kill_active(db))

    def test_per_model_kill_rolls_back_and_history_never_exposes_artifact(self):
        with self.SessionLocal() as db:
            first = self._promoted(db, 1)
            second = self._promoted(db, 2)
            resolution = kill_model_with_incident(
                db, second.model_id, reason="bad calibration", actor="admin:1",
                idempotency_key="model-kill-001", compatibility=self.compatibility,
            )
            self.assertEqual(first.id, resolution.model.id)
            self.assertEqual("rolled_back", resolution.fallback_reason)
            history = serving_version_history(db, user_id=1)
            self.assertEqual(2, len(history))
            self.assertTrue(all("artifact_json" not in item for item in history))
            self.assertTrue(all("evaluation_metrics" not in item for item in history))

    def test_readiness_is_non_sensitive_and_deterministic_is_always_ready(self):
        with self.SessionLocal() as db:
            value = personalization_readiness(db, PersonalizationRuntimeConfig())
            self.assertTrue(value["ready"])
            self.assertTrue(value["deterministic_scheduling_available"])
            self.assertFalse(value["contains_model_parameters"])
            self.assertFalse(value["contains_user_data"])


if __name__ == "__main__":
    unittest.main()
