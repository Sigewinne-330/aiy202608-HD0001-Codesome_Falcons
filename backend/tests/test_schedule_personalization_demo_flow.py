import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base, get_db  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import SchedulingModelPrediction  # noqa: E402
from models.task_new import Task  # noqa: E402
from routers.scheduling_personalization import router  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.schedule_adaptive_ranking import SafeCandidateSnapshot  # noqa: E402
from services.schedule_effort_model import predict_effort_distribution  # noqa: E402
from services.schedule_features import derive_sufficient_statistics  # noqa: E402
from services.schedule_labels import derive_outcome_label  # noqa: E402
from services.schedule_personalization_config import PersonalizationRuntimeConfig  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_personalization_operations import set_global_kill  # noqa: E402
from services.schedule_personalization_serving import serve_personalization  # noqa: E402


class SchedulePersonalizationDemoFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False)
        cls.api = FastAPI()
        cls.api.include_router(router)
        cls.api.dependency_overrides[get_db] = cls._db_dependency
        cls.api.dependency_overrides[get_current_user] = cls._current_user
        cls.client = TestClient(cls.api)
        cls.runtime = PersonalizationRuntimeConfig(
            master_enabled=True, observation_capture_enabled=True,
            modeling_enabled=True, shadow_enabled=True,
        )

    @classmethod
    def _db_dependency(cls):
        with cls.SessionLocal() as db:
            yield db

    @classmethod
    def _current_user(cls):
        with cls.SessionLocal() as db:
            return db.query(AppUser).filter_by(id=1).one()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.SessionLocal() as db:
            db.add(AppUser(username="demo-flow", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            db.add_all([
                Task(user_id=1, title=f"Economics observation {index}", subject="Economics", schedule_kind="essay_draft", status="todo")
                for index in range(5)
            ])
            db.commit()

    def _post(self, path, payload):
        with patch("routers.scheduling_personalization.personalization_runtime_config", self.runtime):
            response = self.client.post(path, json=payload)
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_consent_to_five_observations_effort_dashboard_shadow_and_killed_fallback(self):
        with patch("routers.scheduling_personalization.personalization_runtime_config", self.runtime):
            settings = self.client.get("/api/scheduling/personalization/settings")
            self.assertFalse(settings.json()["operational_personalization_enabled"])
            enabled = self.client.put("/api/scheduling/personalization/settings", json={
                "operational_personalization_enabled": True,
                "work_session_capture_enabled": True,
                "llm_memory_enabled": False,
                "cross_user_learning_enabled": False,
                "near_tie_exploration_enabled": False,
                "raw_event_retention_days": 365,
                "rebuild_after_reset_enabled": False,
                "expected_version": settings.json()["version"],
            })
            self.assertTrue(enabled.json()["effective"]["work_session_capture"])

        for index in range(1, 6):
            started = self._post("/api/scheduling/work-sessions/start", {
                "source": {"source_type": "task", "source_id": index},
                "idempotency_key": f"demo-start-{index:04d}",
                "timezone": "Asia/Shanghai",
            })
            self._post(f"/api/scheduling/work-sessions/{started['session']['id']}/stop", {
                "idempotency_key": f"demo-stop-{index:04d}",
            })
            self._post("/api/scheduling/outcomes", {
                "source": {"source_type": "task", "source_id": index},
                "idempotency_key": f"demo-outcome-{index:04d}",
                "terminal_state": "completed",
                "actual_active_minutes": 45 + index * 5,
                "progress_ratio": 1,
            })

        reference = date.today()
        with self.SessionLocal() as db:
            for index in range(1, 6):
                derive_outcome_label(
                    db, 1, "task", index,
                    outcome_cutoff_at=datetime.now().replace(microsecond=0),
                    derivation_version=f"demo-label-v1-{index}",
                )
            derive_sufficient_statistics(db, 1, reference_date=reference)
            prediction = predict_effort_distribution(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=reference
            )
            db.add(SchedulingModelPrediction(
                prediction_id="demo-dashboard-prediction", user_id=1,
                context_hash="d" * 64, prediction_type="effort",
                p10=prediction.p10_active_minutes, p50=prediction.p50_active_minutes,
                p90=prediction.p90_active_minutes, evidence_maturity=prediction.maturity_score,
                calibration_state=prediction.calibration_state, feature_contributions={},
                serving_mode="shadow", latency_ms=1, eligibility_watermark=1,
            ))
            db.commit()
            dashboard = self.client.get("/api/scheduling/personalization/dashboard")
            self.assertEqual(200, dashboard.status_code, dashboard.text)
            self.assertIsNotNone(dashboard.json()["effort_range"]["p50_minutes"])
            self.assertGreaterEqual(dashboard.json()["evidence"]["eligible_outcomes"], 5)

            candidates = (
                SafeCandidateSnapshot("date:a", date.today(), 1, 1, ("safe",), ("capacity",), 60),
                SafeCandidateSnapshot("date:b", date.today() + timedelta(days=1), 1.01, 2, ("safe",), ("capacity",), 60),
            )
            before = serve_personalization(
                db, user_id=1, candidates=candidates, predictor=None, model=None,
                context_identity="demo-shadow", config=self.runtime,
            )
            self.assertEqual(before.ranking.baseline_order, before.ranking.display_order)
            set_global_kill(db, active=True, reason="demo-kill", actor="demo", idempotency_key="demo-kill-1")
            killed = serve_personalization(
                db, user_id=1, candidates=candidates, predictor=lambda items: (), model=None,
                context_identity="demo-killed", config=self.runtime,
            )
            self.assertEqual("global_kill_switch", killed.fallback_reason)
            self.assertEqual(killed.ranking.baseline_order, killed.ranking.display_order)


if __name__ == "__main__":
    unittest.main()
