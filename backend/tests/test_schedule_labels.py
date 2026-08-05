import sys
import unittest
from datetime import date, datetime, timedelta, timezone
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
from models.schedule_personalization import SchedulingWorkEvent  # noqa: E402
from models.task_new import Task  # noqa: E402
from schemas.schedule_personalization import WorkEventInput  # noqa: E402
from services.schedule_labels import derive_outcome_label  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_work_events import apply_work_event  # noqa: E402


class ScheduleLabelTests(unittest.TestCase):
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
            db.add(AppUser(username="label-user", password="x", balance=10000))
            db.flush()
            db.add(Task(
                user_id=1,
                title="label source",
                estimated_hours=2,
                personal_deadline=date.today() + timedelta(days=2),
                hard_deadline_date=date.today() + timedelta(days=3),
            ))
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            consent.work_session_capture_enabled = True
            db.commit()

    @staticmethod
    def _input(event_type, key, at, **changes):
        values = {
            "event_type": event_type,
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": key,
            "effective_at": at,
            "after_values": {"timezone": "Asia/Shanghai"},
        }
        values.update(changes)
        return WorkEventInput(**values)

    def test_golden_measured_completion_label(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.SessionLocal() as db:
            scheduled = now - timedelta(hours=2)
            apply_work_event(db, 1, self._input("scheduled", "label-schedule-01", scheduled), server_now=now)
            session = apply_work_event(db, 1, self._input(
                "started", "label-start-0001", now - timedelta(hours=1), provenance="active_timer"
            ), server_now=now).session
            apply_work_event(db, 1, self._input(
                "stopped", "label-stop-00001", now, provenance="active_timer"
            ), session_public_id=session.public_id, server_now=now)
            apply_work_event(db, 1, self._input("completed", "label-done-00001", now, progress_ratio=1), server_now=now)
            label = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(minutes=1))
            self.assertEqual("completed", label.terminal_state)
            self.assertFalse(label.is_censored)
            self.assertAlmostEqual(60, float(label.active_minutes))
            self.assertEqual("active_timer_measured", label.active_minutes_provenance)
            self.assertTrue(label.interval_complete)
            self.assertAlmostEqual(0.5, float(label.planned_actual_ratio))
            self.assertAlmostEqual(60, float(label.start_latency_minutes))
            self.assertTrue(label.completed_before_personal_target)
            self.assertTrue(label.completed_before_hard_deadline)

    def test_user_reported_effort_is_proxy_and_abandonment_is_not_failure(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.SessionLocal() as db:
            apply_work_event(db, 1, self._input(
                "abandoned", "label-abandon-01", now,
                active_minutes=90,
                progress_ratio=0.6,
                reason_code="scope_no_longer_valuable",
            ), server_now=now)
            label = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(minutes=1))
            self.assertEqual("reasonably_abandoned", label.terminal_state)
            self.assertFalse(label.is_censored)
            self.assertEqual("user_reported_proxy", label.active_minutes_provenance)
            self.assertFalse(label.interval_complete)
            self.assertAlmostEqual(0.6, float(label.progress_ratio))

    def test_completion_without_duration_does_not_invent_measured_effort(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.SessionLocal() as db:
            apply_work_event(db, 1, self._input("completed", "label-proxy-0001", now), server_now=now)
            label = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(minutes=1))
            self.assertIsNone(label.active_minutes)
            self.assertEqual("completion_proxy_no_effort", label.active_minutes_provenance)
            self.assertFalse(label.interval_complete)

    def test_completion_event_can_close_an_explicit_active_timer(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.SessionLocal() as db:
            apply_work_event(db, 1, self._input(
                "started", "label-open-start", now - timedelta(minutes=30), provenance="active_timer"
            ), server_now=now)
            apply_work_event(db, 1, self._input("completed", "label-close-done", now), server_now=now)
            label = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(minutes=1))
            self.assertAlmostEqual(30, float(label.active_minutes))
            self.assertTrue(label.interval_complete)
            self.assertEqual("active_timer_measured", label.active_minutes_provenance)

    def test_open_and_unknown_outcomes_are_censored_not_negative(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.SessionLocal() as db:
            open_label = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now)
            self.assertTrue(open_label.is_censored)
            self.assertEqual("still_open", open_label.censoring_reason)
            self.assertEqual("unknown", open_label.terminal_state)

            apply_work_event(db, 1, self._input(
                "outcome_observed", "label-unknown-01", now + timedelta(minutes=1),
                after_values={"terminal_state": "unknown"},
                confidence="low",
            ), server_now=now + timedelta(minutes=1))
            unknown = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(minutes=2))
            self.assertTrue(unknown.is_censored)
            self.assertEqual("offline_unknown", unknown.censoring_reason)

    def test_future_events_do_not_leak_across_cutoff(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.SessionLocal() as db:
            future = now + timedelta(hours=2)
            apply_work_event(db, 1, self._input("completed", "label-future-001", future), server_now=future)
            before = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(hours=1))
            self.assertTrue(before.is_censored)
            self.assertEqual("unknown", before.terminal_state)
            after = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=future + timedelta(minutes=1))
            self.assertFalse(after.is_censored)
            self.assertEqual("completed", after.terminal_state)

    def test_confirmed_miss_deletion_reopen_episode_and_idempotent_derivation(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.SessionLocal() as db:
            miss = apply_work_event(db, 1, self._input(
                "outcome_observed", "label-missed-001", now,
                after_values={"terminal_state": "confirmed_miss"},
            ), server_now=now)
            first = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(seconds=1))
            replay = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(seconds=1))
            self.assertEqual(first.id, replay.id)
            self.assertEqual("confirmed_miss", first.terminal_state)
            self.assertFalse(first.is_censored)

            apply_work_event(db, 1, self._input("reopened", "label-reopen-001", now + timedelta(minutes=1)), server_now=now + timedelta(minutes=1))
            apply_work_event(db, 1, self._input("deleted", "label-delete-001", now + timedelta(minutes=2)), server_now=now + timedelta(minutes=2))
            second = derive_outcome_label(db, 1, "task", 1, outcome_cutoff_at=now + timedelta(minutes=3))
            self.assertEqual(2, second.episode)
            self.assertEqual("deleted", second.terminal_state)
            self.assertNotEqual(miss.event.event_id, None)


if __name__ == "__main__":
    unittest.main()
