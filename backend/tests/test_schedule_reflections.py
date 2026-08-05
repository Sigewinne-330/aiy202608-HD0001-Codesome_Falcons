import sys
import unittest
from datetime import datetime, timedelta, timezone
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
from models.task_new import Task  # noqa: E402
from schemas.schedule_personalization import WorkEventInput  # noqa: E402
from services.schedule_personalization_governance import (  # noqa: E402
    get_or_create_private_consent,
    invalidate_memory_entry,
)
from services.schedule_reflections import materialize_reflection_candidate  # noqa: E402
from services.schedule_work_events import apply_work_event  # noqa: E402


class ScheduleReflectionTests(unittest.TestCase):
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
            db.add(AppUser(username="reflection-user", password="x", balance=10000))
            db.flush()
            db.add(Task(user_id=1, title="reflection source"))
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            consent.llm_memory_enabled = True
            db.commit()

    @staticmethod
    def _candidate(evidence, **changes):
        values = {
            "tier": "llm_reflection",
            "memory_key": "writing_duration_pattern",
            "value_json": {"task_archetype": "essay_draft", "duration_multiplier": 1.25},
            "display_text": "Recent essay drafts often took longer than their initial estimate.",
            "evidence_event_ids": evidence,
            "confidence": 0.72,
        }
        values.update(changes)
        return values

    def _events(self, db, count=3):
        base = datetime.now(timezone.utc) - timedelta(days=count)
        event_ids = []
        for index in range(count):
            result = apply_work_event(db, 1, WorkEventInput(
                event_type="progressed",
                source={"source_type": "task", "source_id": 1},
                idempotency_key=f"reflection-event-{index}",
                effective_at=base + timedelta(days=index),
                progress_ratio=(index + 1) / (count + 1),
                confidence="high",
            ), server_now=datetime.now(timezone.utc))
            event_ids.append(UUID(result.event.event_id))
        return event_ids

    def test_weak_or_hallucinated_evidence_abstains(self):
        with self.SessionLocal() as db:
            one = self._events(db, 1)
            weak = materialize_reflection_candidate(
                db, 1, self._candidate(one), generated_by_model="mock", prompt_version="v1"
            )
            self.assertEqual("insufficient_evidence", weak.reason)
            hallucinated = materialize_reflection_candidate(
                db,
                1,
                self._candidate([
                    UUID("11111111-1111-1111-1111-111111111111"),
                    UUID("22222222-2222-2222-2222-222222222222"),
                ]),
                generated_by_model="mock",
                prompt_version="v1",
            )
            self.assertEqual("invalid_evidence", hallucinated.reason)

    def test_valid_reflection_deduplicates_and_deleted_fingerprint_suppresses_recreation(self):
        with self.SessionLocal() as db:
            evidence = self._events(db, 2)
            created = materialize_reflection_candidate(
                db, 1, self._candidate(evidence), generated_by_model="mock", prompt_version="v1"
            )
            self.assertEqual("created", created.state)
            duplicate = materialize_reflection_candidate(
                db, 1, self._candidate(evidence), generated_by_model="mock", prompt_version="v1"
            )
            self.assertEqual("duplicate", duplicate.state)
            invalidate_memory_entry(
                db,
                1,
                created.memory.memory_id,
                suppression_fingerprint=created.memory.suppression_fingerprint,
            )
            suppressed = materialize_reflection_candidate(
                db, 1, self._candidate(evidence), generated_by_model="mock", prompt_version="v1"
            )
            self.assertEqual("suppressed", suppressed.state)

    def test_same_evidence_contradiction_abstains_but_new_evidence_can_supersede(self):
        with self.SessionLocal() as db:
            evidence = self._events(db, 3)
            first = materialize_reflection_candidate(
                db, 1, self._candidate(evidence[:2]), generated_by_model="mock", prompt_version="v1"
            )
            unstable = materialize_reflection_candidate(
                db,
                1,
                self._candidate(evidence[:2], value_json={"duration_multiplier": 0.8}),
                generated_by_model="mock",
                prompt_version="v1",
            )
            self.assertEqual("contradictory_same_evidence", unstable.reason)
            newer = materialize_reflection_candidate(
                db,
                1,
                self._candidate(evidence, value_json={"duration_multiplier": 1.4}),
                generated_by_model="mock",
                prompt_version="v2",
            )
            self.assertEqual("created", newer.state)
            self.assertEqual("contradicted", first.memory.status)
            self.assertEqual(newer.memory.memory_id, first.memory.superseded_by_memory_id)

    def test_prohibited_trait_and_invalid_schema_abstain(self):
        with self.SessionLocal() as db:
            evidence = self._events(db, 2)
            prohibited = materialize_reflection_candidate(
                db,
                1,
                self._candidate(evidence, display_text="The user is lazy and has low intelligence."),
                generated_by_model="mock",
                prompt_version="v1",
            )
            self.assertEqual("prohibited_claim", prohibited.reason)
            malformed = materialize_reflection_candidate(
                db, 1, {"tier": "llm_reflection"}, generated_by_model="mock", prompt_version="v1"
            )
            self.assertEqual("invalid_schema", malformed.reason)


if __name__ == "__main__":
    unittest.main()
