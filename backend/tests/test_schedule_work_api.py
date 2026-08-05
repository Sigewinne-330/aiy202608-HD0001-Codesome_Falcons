import sys
import unittest
from datetime import datetime, timezone
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
from models.schedule_personalization import SchedulingWorkEvent, SchedulingWorkSession  # noqa: E402
from models.task_new import Task  # noqa: E402
from routers.scheduling_personalization import router  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.schedule_personalization_config import PersonalizationRuntimeConfig  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class ScheduleWorkApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False)

        cls.api = FastAPI()
        cls.api.include_router(router)

        def override_db():
            with cls.SessionLocal() as db:
                yield db

        def override_user():
            with cls.SessionLocal() as db:
                return db.query(AppUser).filter_by(id=1).one()

        cls.api.dependency_overrides[get_db] = override_db
        cls.api.dependency_overrides[get_current_user] = override_user
        cls.client = TestClient(cls.api)
        cls.runtime = PersonalizationRuntimeConfig(
            master_enabled=True,
            observation_capture_enabled=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.SessionLocal() as db:
            db.add_all([
                AppUser(username="work-api-one", password="x", balance=10000),
                AppUser(username="work-api-two", password="x", balance=10000),
            ])
            db.flush()
            db.add_all([Task(user_id=1, title="owned"), Task(user_id=2, title="foreign")])
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            consent.work_session_capture_enabled = True
            db.commit()

    def _post(self, path, json):
        with patch("routers.scheduling_personalization.personalization_runtime_config", self.runtime):
            return self.client.post(path, json=json)

    def test_authenticated_dependency_is_present(self):
        unauthenticated = FastAPI()
        unauthenticated.include_router(router)
        unauthenticated.dependency_overrides[get_db] = self.api.dependency_overrides[get_db]
        response = TestClient(unauthenticated).get("/api/scheduling/work-sessions/active")
        self.assertEqual(401, response.status_code)

    def test_settings_are_versioned_server_authoritative_and_keep_deterministic_mode(self):
        with patch("routers.scheduling_personalization.personalization_runtime_config", self.runtime):
            current = self.client.get("/api/scheduling/personalization/settings")
            self.assertEqual(200, current.status_code, current.text)
            self.assertEqual(1, current.json()["version"])
            self.assertTrue(current.json()["deterministic_scheduling_available"])
            updated = self.client.put("/api/scheduling/personalization/settings", json={
                "operational_personalization_enabled": True,
                "work_session_capture_enabled": True,
                "llm_memory_enabled": True,
                "cross_user_learning_enabled": False,
                "near_tie_exploration_enabled": False,
                "raw_event_retention_days": 180,
                "rebuild_after_reset_enabled": False,
                "expected_version": 1,
            })
            self.assertEqual(200, updated.status_code, updated.text)
            self.assertEqual(2, updated.json()["version"])
            self.assertEqual(180, updated.json()["raw_event_retention_days"])
            stale = self.client.put("/api/scheduling/personalization/settings", json={
                "operational_personalization_enabled": True,
                "work_session_capture_enabled": True,
                "expected_version": 1,
            })
            self.assertEqual(409, stale.status_code, stale.text)
            withdrawn = self.client.put("/api/scheduling/personalization/settings", json={
                "expected_version": 2,
            })
            self.assertEqual(200, withdrawn.status_code, withdrawn.text)
            self.assertFalse(withdrawn.json()["operational_personalization_enabled"])
            self.assertEqual(2, withdrawn.json()["eligibility_watermark"])
            self.assertTrue(withdrawn.json()["deterministic_scheduling_available"])

    def test_start_retry_pause_resume_stop_and_active_reconciliation(self):
        started = self._post("/api/scheduling/work-sessions/start", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "api-start-000001",
            "timezone": "Asia/Shanghai",
        })
        self.assertEqual(200, started.status_code, started.text)
        public_id = started.json()["session"]["id"]
        replay = self._post("/api/scheduling/work-sessions/start", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "api-start-000001",
            "timezone": "Asia/Shanghai",
        })
        self.assertFalse(replay.json()["created"])
        self.assertEqual(200, self._post(f"/api/scheduling/work-sessions/{public_id}/pause", {"idempotency_key": "api-pause-00001"}).status_code)
        self.assertEqual("paused", self.client.get("/api/scheduling/work-sessions/active").json()["items"][0]["state"])
        self.assertEqual(200, self._post(f"/api/scheduling/work-sessions/{public_id}/resume", {"idempotency_key": "api-resume-0001"}).status_code)
        stopped = self._post(f"/api/scheduling/work-sessions/{public_id}/stop", {"idempotency_key": "api-stop-000001"})
        self.assertEqual(200, stopped.status_code, stopped.text)
        self.assertEqual("stopped", stopped.json()["session"]["state"])
        self.assertEqual([], self.client.get("/api/scheduling/work-sessions/active").json()["items"])

    def test_disabled_capture_bounds_foreign_session_and_conflict_shapes(self):
        with self.SessionLocal() as db:
            consent = db.query(models.SchedulingConsentSetting).filter_by(user_id=1).one()
            consent.work_session_capture_enabled = False
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            foreign = SchedulingWorkSession(
                public_id="11111111-1111-1111-1111-111111111111",
                user_id=2,
                source_type="task",
                source_id=2,
                active_key="2:task:2",
                state="active",
                timezone="Asia/Shanghai",
                started_at=now,
                current_interval_started_at=now,
            )
            db.add(foreign)
            db.commit()
        disabled = self._post("/api/scheduling/work-sessions/start", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "api-disabled-001",
        })
        self.assertEqual("work_capture_disabled", disabled.json()["excluded_reason"])
        self.assertEqual(404, self._post(
            "/api/scheduling/work-sessions/11111111-1111-1111-1111-111111111111/pause",
            {"idempotency_key": "foreign-pause-01"},
        ).status_code)
        self.assertEqual(422, self._post("/api/scheduling/work-sessions/start", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "short",
        }).status_code)

    def test_outcomes_are_bounded_idempotent_and_corrections_are_append_only(self):
        completed = self._post("/api/scheduling/outcomes", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "api-outcome-0001",
            "terminal_state": "completed",
            "actual_active_minutes": 45,
            "progress_ratio": 1,
        })
        self.assertEqual(200, completed.status_code, completed.text)
        event_id = completed.json()["event_id"]
        replay = self._post("/api/scheduling/outcomes", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "api-outcome-0001",
            "terminal_state": "completed",
            "actual_active_minutes": 45,
            "progress_ratio": 1,
        })
        self.assertFalse(replay.json()["created"])
        corrected = self._post("/api/scheduling/outcomes", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "api-correct-0001",
            "terminal_state": "completed",
            "actual_active_minutes": 50,
            "progress_ratio": 1,
            "correction_of_event_id": event_id,
        })
        self.assertEqual("corrected", corrected.json()["event_type"])
        self.assertEqual(422, self._post("/api/scheduling/outcomes", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "api-invalid-0001",
            "progress_ratio": 1.5,
        }).status_code)
        with self.SessionLocal() as db:
            self.assertEqual(2, db.query(SchedulingWorkEvent).count())

    def test_forgotten_session_reconciliation_is_explicit_and_discardable(self):
        started = self._post("/api/scheduling/work-sessions/start", {
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": "api-forgot-start",
        })
        public_id = started.json()["session"]["id"]
        reconciled = self._post(f"/api/scheduling/work-sessions/{public_id}/stop", {
            "idempotency_key": "api-forgot-drop1",
            "reconciliation_action": "discard",
            "effective_at": datetime.now(timezone.utc).isoformat(),
        })
        self.assertEqual(200, reconciled.status_code, reconciled.text)
        self.assertEqual("discarded", reconciled.json()["session"]["state"])

    def test_unexpected_storage_failure_returns_recoverable_503(self):
        with patch("routers.scheduling_personalization.personalization_runtime_config", self.runtime), patch(
            "routers.scheduling_personalization.apply_work_event",
            side_effect=RuntimeError("database unavailable"),
        ):
            response = self.client.post("/api/scheduling/work-sessions/start", json={
                "source": {"source_type": "task", "source_id": 1},
                "idempotency_key": "api-failure-0001",
            })
        self.assertEqual(503, response.status_code, response.text)
        with self.SessionLocal() as db:
            self.assertEqual(0, db.query(SchedulingWorkEvent).count())


if __name__ == "__main__":
    unittest.main()
