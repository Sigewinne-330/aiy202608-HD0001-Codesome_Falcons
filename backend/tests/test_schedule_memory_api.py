import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

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
from models.task_new import Task  # noqa: E402
from routers.scheduling_personalization import router  # noqa: E402
from schemas.schedule_personalization import MemoryEntryInput, WorkEventInput  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.schedule_memory import create_memory_entry  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_work_events import apply_work_event  # noqa: E402


class ScheduleMemoryApiTests(unittest.TestCase):
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

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.SessionLocal() as db:
            db.add_all([
                AppUser(username="memory-api-one", password="x", balance=10000),
                AppUser(username="memory-api-two", password="x", balance=10000),
            ])
            db.flush()
            db.add_all([Task(user_id=1, title="owned source"), Task(user_id=2, title="foreign source")])
            for user_id in (1, 2):
                consent = get_or_create_private_consent(db, user_id)
                consent.operational_personalization_enabled = True
                consent.llm_memory_enabled = True
            db.commit()

    @staticmethod
    def _explicit(db, user_id, index):
        return create_memory_entry(db, user_id, MemoryEntryInput(
            tier="explicit_declaration",
            memory_key=f"preference_{index}",
            value_json={"minutes": 30 + index},
            display_text=f"Preference {index}",
        ), source="user")

    def test_owner_scoped_pagination_detail_and_explicit_edit_history(self):
        with self.SessionLocal() as db:
            owned = [self._explicit(db, 1, index) for index in range(3)]
            foreign = self._explicit(db, 2, 9)
            db.commit()
            owned_ids = {row.memory_id for row in owned}
            foreign_id = foreign.memory_id
        first = self.client.get("/api/scheduling/memory", params={"limit": 2})
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(2, len(first.json()["items"]))
        self.assertTrue(first.json()["next_cursor"])
        second = self.client.get("/api/scheduling/memory", params={
            "limit": 2,
            "before": first.json()["next_cursor"],
        })
        seen = {item["memory_id"] for item in first.json()["items"] + second.json()["items"]}
        self.assertEqual(owned_ids, seen)
        self.assertEqual(404, self.client.get(f"/api/scheduling/memory/{foreign_id}").status_code)

        memory_id = first.json()["items"][0]["memory_id"]
        edited = self.client.put(f"/api/scheduling/memory/{memory_id}", json={
            "value_json": {"minutes": 55},
            "display_text": "Updated preference",
        })
        self.assertEqual(200, edited.status_code, edited.text)
        self.assertNotEqual(memory_id, edited.json()["memory_id"])
        old = self.client.get(f"/api/scheduling/memory/{memory_id}")
        self.assertEqual("superseded", old.json()["status"])

    def test_reflection_is_not_editable_delete_is_immediate_and_missing_source_is_visible(self):
        with self.SessionLocal() as db:
            now = datetime.now(timezone.utc)
            evidence = apply_work_event(db, 1, WorkEventInput(
                event_type="progressed",
                source={"source_type": "task", "source_id": 1},
                idempotency_key="memory-api-evidence",
                effective_at=now,
                progress_ratio=0.5,
            ), server_now=now)
            reflection = create_memory_entry(db, 1, MemoryEntryInput(
                tier="llm_reflection",
                memory_key="duration_pattern",
                value_json={"multiplier": 1.2},
                display_text="Work may take longer.",
                evidence_event_ids=[UUID(evidence.event.event_id)],
                confidence=0.7,
            ), source="llm", generated_by_model="mock", prompt_version="v1")
            memory_id = reflection.memory_id
            db.query(Task).filter_by(id=1).delete()
            db.commit()
        detail = self.client.get(f"/api/scheduling/memory/{memory_id}")
        self.assertEqual(200, detail.status_code, detail.text)
        self.assertFalse(detail.json()["evidence"][0]["source_available"])
        self.assertEqual(409, self.client.put(
            f"/api/scheduling/memory/{memory_id}",
            json={"display_text": "Attempted rewrite"},
        ).status_code)
        deleted = self.client.delete(f"/api/scheduling/memory/{memory_id}")
        self.assertEqual(200, deleted.status_code, deleted.text)
        self.assertEqual("deleted", deleted.json()["status"])
        current = self.client.get("/api/scheduling/memory")
        self.assertNotIn(memory_id, [item["memory_id"] for item in current.json()["items"]])

    def test_export_reset_and_deletion_status_routes_form_a_recoverable_control_loop(self):
        with self.SessionLocal() as db:
            memory = self._explicit(db, 1, 1)
            db.commit()
            memory_id = memory.memory_id
        exported = self.client.get("/api/scheduling/memory/export")
        self.assertEqual(200, exported.status_code, exported.text)
        self.assertEqual("scheduling-personalization-export.v1", exported.json()["schema_version"])
        self.assertIn(memory_id, [row["memory_id"] for row in exported.json()["memories"]])
        reset = self.client.post("/api/scheduling/personalization/reset", json={
            "idempotency_key": "memory-api-reset",
            "rebuild_from_retained_evidence": False,
            "expected_settings_version": 1,
        })
        self.assertEqual(200, reset.status_code, reset.text)
        self.assertTrue(reset.json()["raw_evidence_preserved"])
        self.assertTrue(reset.json()["deterministic_scheduling_available"])
        replay = self.client.post("/api/scheduling/personalization/reset", json={
            "idempotency_key": "memory-api-reset",
            "rebuild_from_retained_evidence": False,
            "expected_settings_version": 1,
        })
        self.assertEqual(200, replay.status_code, replay.text)
        status = self.client.get("/api/scheduling/personalization/deletion-status")
        self.assertEqual(200, status.status_code, status.text)
        self.assertEqual("pending", status.json()["state"])
        self.assertNotIn("job_id", status.text)


if __name__ == "__main__":
    unittest.main()
