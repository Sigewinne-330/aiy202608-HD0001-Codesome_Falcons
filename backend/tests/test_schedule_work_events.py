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
from models.schedule_personalization import SchedulingWorkEvent, SchedulingWorkSession  # noqa: E402
from models.task_new import Task  # noqa: E402
from schemas.schedule_personalization import WorkEventInput  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_work_events import (  # noqa: E402
    WorkEventConflict,
    WorkEventNotFound,
    WorkEventRateLimited,
    WorkEventStale,
    apply_work_event,
    reconcile_work_session,
    split_interval_by_local_date,
)


class ScheduleWorkEventTests(unittest.TestCase):
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
                AppUser(username="worker-one", password="x", balance=10000),
                AppUser(username="worker-two", password="x", balance=10000),
            ])
            db.flush()
            db.add(Task(user_id=1, title="work source"))
            db.commit()

    @staticmethod
    def _enable(db, user_id=1):
        consent = get_or_create_private_consent(db, user_id)
        consent.operational_personalization_enabled = True
        consent.work_session_capture_enabled = True
        db.flush()

    @staticmethod
    def _event(event_type, key, effective_at, **changes):
        values = {
            "event_type": event_type,
            "source": {"source_type": "task", "source_id": 1},
            "idempotency_key": key,
            "effective_at": effective_at,
            "after_values": {"timezone": "Asia/Shanghai"},
        }
        values.update(changes)
        return WorkEventInput(**values)

    def test_start_pause_resume_stop_excludes_paused_duration(self):
        start = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            self._enable(db)
            started = apply_work_event(db, 1, self._event("started", "timer-start-0001", start), server_now=start)
            public_id = started.session.public_id
            apply_work_event(db, 1, self._event("paused", "timer-pause-0001", start + timedelta(minutes=30)), session_public_id=public_id, server_now=start + timedelta(minutes=30))
            replayed_pause = apply_work_event(db, 1, self._event("paused", "timer-pause-0001", start + timedelta(minutes=30)), session_public_id=public_id, server_now=start + timedelta(minutes=30))
            self.assertFalse(replayed_pause.created)
            apply_work_event(db, 1, self._event("resumed", "timer-resume-001", start + timedelta(minutes=50)), session_public_id=public_id, server_now=start + timedelta(minutes=50))
            stopped = apply_work_event(db, 1, self._event("stopped", "timer-stop-00001", start + timedelta(minutes=70)), session_public_id=public_id, server_now=start + timedelta(minutes=70))
            self.assertEqual("stopped", stopped.session.state)
            self.assertEqual(50 * 60, stopped.session.accumulated_active_seconds)
            self.assertIsNone(stopped.session.active_key)
            self.assertEqual(["started", "paused", "resumed", "stopped"], [
                row.event_type for row in db.query(SchedulingWorkEvent).order_by(SchedulingWorkEvent.id).all()
            ])

    def test_duplicate_is_idempotent_changed_retry_conflicts_and_second_start_is_rejected(self):
        now = datetime(2026, 8, 5, 2, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            self._enable(db)
            data = self._event("started", "duplicate-start-1", now)
            first = apply_work_event(db, 1, data, server_now=now)
            second = apply_work_event(db, 1, data, server_now=now)
            self.assertFalse(second.created)
            self.assertEqual(first.event.id, second.event.id)
            with self.assertRaises(WorkEventConflict):
                apply_work_event(db, 1, self._event("paused", "duplicate-start-1", now), session_public_id=first.session.public_id, server_now=now)
            with self.assertRaises(WorkEventConflict):
                apply_work_event(db, 1, self._event("started", "second-start-001", now), server_now=now)
            self.assertEqual(1, db.query(SchedulingWorkSession).count())

    def test_stale_transition_is_rejected_without_mutating_session(self):
        start = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            self._enable(db)
            session = apply_work_event(db, 1, self._event("started", "stale-start-0001", start), server_now=start).session
            apply_work_event(db, 1, self._event("paused", "stale-pause-0001", start + timedelta(minutes=20)), session_public_id=session.public_id, server_now=start + timedelta(minutes=20))
            with self.assertRaises(WorkEventStale):
                apply_work_event(db, 1, self._event("resumed", "stale-resume-001", start + timedelta(minutes=10)), session_public_id=session.public_id, server_now=start + timedelta(minutes=30))
            self.assertEqual("paused", session.state)
            self.assertEqual(20 * 60, session.accumulated_active_seconds)

    def test_forgotten_timer_can_stop_with_low_confidence_or_discard_open_interval(self):
        start = datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            self._enable(db)
            first = apply_work_event(db, 1, self._event("started", "forgot-start-0001", start), server_now=start)
            reconciled = reconcile_work_session(
                db, 1, first.session.public_id,
                effective_at=start + timedelta(hours=2),
                idempotency_key="forgot-stop-00001",
                action="stop",
                server_now=start + timedelta(hours=3),
            )
            self.assertEqual("low", reconciled.event.confidence)
            self.assertEqual(2 * 3600, reconciled.session.accumulated_active_seconds)

            second_start = start + timedelta(hours=4)
            second = apply_work_event(db, 1, self._event("started", "forgot-start-0002", second_start), server_now=second_start)
            discarded = reconcile_work_session(
                db, 1, second.session.public_id,
                effective_at=second_start + timedelta(hours=5),
                idempotency_key="forgot-drop-00001",
                action="discard",
                server_now=second_start + timedelta(hours=6),
            )
            self.assertEqual("discarded", discarded.session.state)
            self.assertEqual(0, discarded.session.accumulated_active_seconds)

    def test_cross_midnight_interval_is_one_fact_with_deterministic_daily_splits(self):
        start = datetime(2026, 8, 5, 15, 30, tzinfo=timezone.utc)  # 23:30 Shanghai
        end = start + timedelta(hours=2)
        pieces = split_interval_by_local_date(start, end, "Asia/Shanghai")
        self.assertEqual([(date(2026, 8, 5), 1800), (date(2026, 8, 6), 5400)], pieces)
        with self.SessionLocal() as db:
            self._enable(db)
            session = apply_work_event(db, 1, self._event("started", "midnight-start-1", start), server_now=start).session
            stopped = apply_work_event(db, 1, self._event("stopped", "midnight-stop-01", end), session_public_id=session.public_id, server_now=end)
            self.assertEqual(7200, stopped.session.accumulated_active_seconds)
            self.assertEqual(2, db.query(SchedulingWorkEvent).count())

    def test_lifecycle_events_correction_ownership_and_disabled_capture(self):
        now = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            self._enable(db)
            progressed = apply_work_event(db, 1, self._event(
                "progressed", "progress-event-1", now,
                progress_ratio=0.4,
                active_minutes=25,
            ), server_now=now)
            corrected = apply_work_event(db, 1, self._event(
                "corrected", "correct-event-1", now + timedelta(minutes=1),
                correction_of_event_id=progressed.event.event_id,
                after_values={"progress_ratio": 0.5},
            ), server_now=now + timedelta(minutes=1))
            self.assertEqual(progressed.event.event_id, corrected.event.correction_of_event_id)
            self.assertEqual(0.5, corrected.event.after_values["progress_ratio"])
            with self.assertRaises(WorkEventNotFound):
                apply_work_event(db, 2, self._event("completed", "foreign-event-01", now), server_now=now)
            db.rollback()
            disabled = apply_work_event(db, 1, self._event("started", "disabled-start-1", now), server_now=now)
            self.assertEqual("consent_disabled", disabled.skipped_reason)

    def test_all_non_timer_lifecycle_events_are_typed_and_completion_closes_timer(self):
        now = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            self._enable(db)
            session = apply_work_event(
                db, 1, self._event("started", "lifecycle-start-1", now), server_now=now
            ).session
            completed = apply_work_event(
                db,
                1,
                self._event("completed", "lifecycle-done-01", now + timedelta(minutes=15)),
                server_now=now + timedelta(minutes=15),
            )
            self.assertEqual(session.id, completed.session.id)
            self.assertEqual("stopped", completed.session.state)
            self.assertEqual(15 * 60, completed.session.accumulated_active_seconds)

            event_types = [
                "created",
                "estimated",
                "scheduled",
                "moved",
                "progressed",
                "abandoned",
                "deleted",
                "reopened",
                "deadline_changed",
            ]
            for index, event_type in enumerate(event_types, start=1):
                apply_work_event(
                    db,
                    1,
                    self._event(
                        event_type,
                        f"lifecycle-{index:08d}",
                        now + timedelta(minutes=15 + index),
                    ),
                    server_now=now + timedelta(minutes=15 + index),
                )
            persisted = {row.event_type for row in db.query(SchedulingWorkEvent).all()}
            self.assertTrue(set(event_types) <= persisted)

    def test_new_events_are_rate_limited_but_idempotent_retry_remains_available(self):
        now = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            self._enable(db)
            first_data = self._event("progressed", "rate-first-00001", now, progress_ratio=0.1)
            first = apply_work_event(
                db, 1, first_data, server_now=now, rate_limit_per_minute=1
            )
            replay = apply_work_event(
                db, 1, first_data, server_now=now, rate_limit_per_minute=1
            )
            self.assertFalse(replay.created)
            self.assertEqual(first.event.id, replay.event.id)
            with self.assertRaises(WorkEventRateLimited):
                apply_work_event(
                    db,
                    1,
                    self._event("progressed", "rate-second-0001", now, progress_ratio=0.2),
                    server_now=now,
                    rate_limit_per_minute=1,
                )


if __name__ == "__main__":
    unittest.main()
