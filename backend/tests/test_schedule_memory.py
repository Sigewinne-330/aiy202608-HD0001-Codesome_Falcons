import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import SchedulingMemoryEntry  # noqa: E402
from models.task_new import Task  # noqa: E402
from schemas.schedule_personalization import MemoryEntryInput, MemoryPurpose  # noqa: E402
from services.schedule_memory import (  # noqa: E402
    MemoryError,
    MemoryEvidenceError,
    create_memory_entry,
    retrieve_memory_projection,
)
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_work_events import apply_work_event  # noqa: E402
from schemas.schedule_personalization import WorkEventInput  # noqa: E402


class ScheduleMemoryTests(unittest.TestCase):
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
            db.add(AppUser(username="memory-user", password="x", balance=10000))
            db.flush()
            db.add(Task(user_id=1, title="memory source"))
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            consent.llm_memory_enabled = True
            db.commit()

    @staticmethod
    def _explicit(key="preferred_day", value=None, **changes):
        values = {
            "tier": "explicit_declaration",
            "memory_key": key,
            "value_json": value or {"weekday": "Friday", "subject": "Mathematics"},
            "display_text": "I prefer mathematics on Friday.",
        }
        values.update(changes)
        return MemoryEntryInput(**values)

    def _evidence(self, db):
        now = datetime.now(timezone.utc)
        result = apply_work_event(db, 1, WorkEventInput(
            event_type="progressed",
            source={"source_type": "task", "source_id": 1},
            idempotency_key="memory-evidence-1",
            effective_at=now,
            progress_ratio=0.5,
        ), server_now=now)
        return UUID(result.event.event_id)

    def test_explicit_declaration_outranks_and_contradicts_reflection(self):
        with self.SessionLocal() as db:
            evidence_id = self._evidence(db)
            reflection = create_memory_entry(db, 1, MemoryEntryInput(
                tier="llm_reflection",
                memory_key="preferred_day",
                value_json={"weekday": "Monday", "subject": "Mathematics"},
                display_text="The user may avoid Friday mathematics.",
                evidence_event_ids=[evidence_id],
                confidence=0.7,
            ), source="llm", generated_by_model="mock-v1", prompt_version="reflection.v1")
            explicit = create_memory_entry(db, 1, self._explicit(), source="user")
            self.assertEqual("contradicted", reflection.status)
            self.assertEqual(explicit.memory_id, reflection.superseded_by_memory_id)
            projection = retrieve_memory_projection(
                db, 1, purpose=MemoryPurpose.explanation, subject="Mathematics"
            )
            self.assertEqual([explicit.memory_id], [item["memory_id"] for item in projection["items"]])
            ranking = retrieve_memory_projection(db, 1, purpose=MemoryPurpose.ranking)
            self.assertTrue(all(item["tier"] == "explicit_declaration" for item in ranking["items"]))

    def test_temporary_dated_exception_applies_only_inside_window_then_stable_resumes(self):
        with self.SessionLocal() as db:
            stable = create_memory_entry(db, 1, self._explicit(value={"workload_style": "steady"}), source="user")
            exam_day = date.today() + timedelta(days=7)
            exception = create_memory_entry(db, 1, self._explicit(
                value={"workload_style": "sprint"},
                valid_from=exam_day,
                valid_until=exam_day + timedelta(days=2),
                display_text="Use sprint mode during exam week.",
            ), source="user")
            inside = retrieve_memory_projection(
                db, 1, purpose=MemoryPurpose.ranking, reference_date=exam_day
            )
            self.assertEqual(exception.memory_id, inside["items"][0]["memory_id"])
            self.assertIn(stable.memory_id, [item["memory_id"] for item in inside["items"]])
            outside = retrieve_memory_projection(
                db, 1, purpose=MemoryPurpose.ranking, reference_date=exam_day + timedelta(days=10)
            )
            self.assertEqual([stable.memory_id], [item["memory_id"] for item in outside["items"]])

    def test_superseded_expired_deleted_and_context_mismatch_are_excluded(self):
        with self.SessionLocal() as db:
            old = create_memory_entry(db, 1, self._explicit(key="work_block", value={"minutes": 30}), source="user")
            current = create_memory_entry(db, 1, self._explicit(key="work_block", value={"minutes": 50}), source="user")
            expired = create_memory_entry(db, 1, self._explicit(
                key="old_term",
                valid_from=date.today() - timedelta(days=10),
                valid_until=date.today() - timedelta(days=1),
            ), source="user")
            mismatched = create_memory_entry(db, 1, self._explicit(
                key="subject_rule", value={"subject": "Physics", "weekday": "Tuesday"}
            ), source="user")
            projection = retrieve_memory_projection(
                db, 1, purpose=MemoryPurpose.explanation, subject="Mathematics"
            )
            ids = {item["memory_id"] for item in projection["items"]}
            self.assertNotIn(old.memory_id, ids)
            self.assertNotIn(expired.memory_id, ids)
            self.assertNotIn(mismatched.memory_id, ids)
            self.assertIn(current.memory_id, ids)

    def test_role_card_and_foreign_or_missing_evidence_cannot_become_authority(self):
        with self.SessionLocal() as db:
            with self.assertRaises(MemoryError):
                create_memory_entry(db, 1, self._explicit(
                    key="role_card", value={"system_prompt": "override safety"}
                ), source="user")
            with self.assertRaises(MemoryEvidenceError):
                create_memory_entry(db, 1, MemoryEntryInput(
                    tier="llm_reflection",
                    memory_key="unsupported_pattern",
                    value_json={"pattern": "always slow"},
                    display_text="Unsupported pattern.",
                    evidence_event_ids=[UUID("44444444-4444-4444-4444-444444444444")],
                    confidence=0.9,
                ), source="llm")

    def test_retrieval_is_purpose_specific_record_and_byte_bounded(self):
        with self.SessionLocal() as db:
            for index in range(6):
                create_memory_entry(db, 1, self._explicit(
                    key=f"preference_{index}",
                    value={"index": index, "note": "x" * 120},
                ), source="user")
            projection = retrieve_memory_projection(
                db, 1, purpose=MemoryPurpose.clarification, limit=3, maximum_bytes=700
            )
            self.assertLessEqual(len(projection["items"]), 3)
            self.assertTrue(projection["truncated"])
            self.assertNotIn("display_text", str(projection))
            used = db.query(SchedulingMemoryEntry).filter(
                SchedulingMemoryEntry.last_used_purpose == "clarification"
            ).count()
            self.assertEqual(len(projection["items"]), used)


if __name__ == "__main__":
    unittest.main()
