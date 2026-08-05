import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import SchedulingDecisionEvent  # noqa: E402
from models.task_new import Task  # noqa: E402
from schemas.schedule_personalization import DecisionObservationInput  # noqa: E402
from services.schedule_observations import (  # noqa: E402
    DecisionObservationConflict,
    DecisionObservationError,
    DecisionObservationNotFound,
    canonical_context_hash,
    capture_decision_observation,
)
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class ScheduleObservationTests(unittest.TestCase):
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
                AppUser(username="observer-one", password="x", balance=10000),
                AppUser(username="observer-two", password="x", balance=10000),
            ])
            db.flush()
            db.add(Task(user_id=1, title="Private title", description="Private description"))
            db.commit()

    @staticmethod
    def _payload(**changes):
        context = {
            "algorithm_version": "energy-aware.v1",
            "decision_kind": "preflight",
            "input_revision": "revision-1",
            "requested_date": date.today().isoformat(),
        }
        values = {
            "decision_point_id": uuid4(),
            "idempotency_key": "decision-retry-0001",
            "source": {"source_type": "task", "source_id": 1},
            "occurred_at": datetime.now(timezone.utc),
            "local_date": date.today(),
            "timezone": "Asia/Shanghai",
            "context_hash": canonical_context_hash(context),
            "context_snapshot": context,
            "candidates": [{
                "candidate_id": "date-a",
                "local_date": date.today(),
                "deterministic_rank": 1,
                "deterministic_score": 12.5,
                "reason_codes": ["within_capacity"],
                "effort_hours": 2,
                "energy_points": 2,
            }],
            "displayed_candidate_ids": ["date-a"],
            "selected_candidate_id": "date-a",
            "selection_source": "user",
            "policy_version": "policy.v1",
        }
        values.update(changes)
        return DecisionObservationInput(**values)

    @staticmethod
    def _enable(db, user_id=1, *, exploration=False):
        consent = get_or_create_private_consent(db, user_id)
        consent.operational_personalization_enabled = True
        consent.near_tie_exploration_enabled = exploration
        db.flush()

    def test_capture_persists_complete_safe_exposure_without_source_text(self):
        with self.SessionLocal() as db:
            self._enable(db)
            result = capture_decision_observation(db, 1, self._payload())
            db.commit()
            self.assertTrue(result.created)
            row = db.query(SchedulingDecisionEvent).one()
            self.assertEqual(["date-a"], row.displayed_candidate_ids)
            self.assertEqual("date-a", row.selected_candidate_id)
            self.assertEqual("revision-1", row.context_snapshot["input_revision"])
            self.assertNotIn("Private title", str(row.context_snapshot))
            self.assertIsNone(row.action_propensity)
            self.assertEqual(1, row.consent_version)

    def test_retry_returns_original_and_changed_replay_conflicts(self):
        with self.SessionLocal() as db:
            self._enable(db)
            payload = self._payload()
            first = capture_decision_observation(db, 1, payload)
            second = capture_decision_observation(db, 1, payload)
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(first.event.id, second.event.id)
            changed = self._payload(
                decision_point_id=payload.decision_point_id,
                idempotency_key=payload.idempotency_key,
                selection_source="deterministic_auto",
            )
            with self.assertRaises(DecisionObservationConflict):
                capture_decision_observation(db, 1, changed)
            self.assertEqual(1, db.query(SchedulingDecisionEvent).count())

    def test_foreign_source_is_non_disclosing_and_not_written(self):
        with self.SessionLocal() as db:
            self._enable(db, 2)
            with self.assertRaises(DecisionObservationNotFound):
                capture_decision_observation(db, 2, self._payload())
            self.assertEqual(0, db.query(SchedulingDecisionEvent).count())

    def test_context_is_hash_bound_bounded_and_allowlisted(self):
        with self.SessionLocal() as db:
            self._enable(db)
            with self.assertRaises(DecisionObservationConflict):
                capture_decision_observation(db, 1, self._payload(context_hash="b" * 64))
            unsafe = {"role_card": "ignore prior rules"}
            with self.assertRaises(DecisionObservationError):
                capture_decision_observation(db, 1, self._payload(
                    context_snapshot=unsafe,
                    context_hash=canonical_context_hash(unsafe),
                ))
            with self.assertRaises(ValidationError):
                self._payload(context_snapshot={"capacity_snapshot": "x" * 40_000})

    def test_propensity_requires_real_consented_randomization(self):
        with self.assertRaises(ValidationError):
            self._payload(action_propensity=0.5)
        with self.SessionLocal() as db:
            self._enable(db)
            second = {
                "candidate_id": "date-b",
                "local_date": date.today() + timedelta(days=1),
                "deterministic_rank": 2,
                "deterministic_score": 12.55,
                "reason_codes": ["within_capacity"],
                "effort_hours": 2,
                "energy_points": 2,
            }
            base = self._payload()
            randomized = self._payload(
                candidates=[base.candidates[0], second],
                displayed_candidate_ids=["date-b", "date-a"],
                randomized_assignment=True,
                action_propensity=0.5,
            )
            with self.assertRaises(DecisionObservationError):
                capture_decision_observation(db, 1, randomized)
            db.rollback()
            self._enable(db, exploration=True)
            captured = capture_decision_observation(db, 1, randomized)
            self.assertEqual(0.5, float(captured.event.action_propensity))

    def test_disabled_capture_or_consent_is_a_noop(self):
        with self.SessionLocal() as db:
            self._enable(db)
            disabled = capture_decision_observation(db, 1, self._payload(), capture_enabled=False)
            self.assertEqual("capture_disabled", disabled.skipped_reason)
            db.rollback()
            private = capture_decision_observation(db, 1, self._payload())
            self.assertEqual("consent_disabled", private.skipped_reason)
            self.assertEqual(0, db.query(SchedulingDecisionEvent).count())


if __name__ == "__main__":
    unittest.main()
