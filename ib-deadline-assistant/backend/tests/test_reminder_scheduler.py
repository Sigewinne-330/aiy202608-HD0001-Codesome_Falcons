import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models.deadline import Deadline, DeadlineStatus  # noqa: E402
from models.reminder import (  # noqa: E402
    ReminderDigest,
    ReminderOccurrence,
    ReminderOccurrenceState,
)
from models.task_new import Task as AppTask, TaskType  # noqa: E402
from models.user import User  # noqa: E402
from services.reminder_preferences import resolve_preferences  # noqa: E402
from services.reminder_scheduler import (  # noqa: E402
    claim_daily_digest,
    finalize_digest_snapshot,
    list_reminder_candidates,
    local_run_context,
)
from services.reminder_seeds import seed_builtin_role_cards  # noqa: E402


class ReminderSchedulerTests(unittest.TestCase):
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
            db.add_all(
                [
                    User(username="one", email="one@example.com", password="x"),
                    User(username="two", email="two@example.com", password="x"),
                ]
            )
            db.commit()
            seed_builtin_role_cards(db)

    def test_candidate_query_includes_three_categories_without_limit(self):
        local_day = date(2026, 8, 3)
        with self.SessionLocal() as db:
            process = AppTask(
                user_id=1,
                title="Process container",
                task_type=TaskType.process,
                status="todo",
                deadline=datetime(2026, 8, 5),
            )
            db.add(process)
            db.flush()
            db.add(
                AppTask(
                    user_id=1,
                    title="Process child",
                    status="in_progress",
                    deadline=datetime(2026, 8, 5),
                )
            )
            for index in range(55):
                db.add(
                    AppTask(
                        user_id=1,
                        title=f"Todo {index}",
                        task_type=TaskType.todo,
                        status="todo",
                        deadline=datetime(2026, 8, 4),
                    )
                )
            db.add_all(
                [
                    AppTask(
                        user_id=1,
                        title="Done",
                        status="done",
                        deadline=datetime(2026, 8, 4),
                    ),
                    AppTask(user_id=1, title="No date", status="todo"),
                    Deadline(
                        user_id=1,
                        title="External deadline",
                        due_date=date(2026, 8, 3),
                        status=DeadlineStatus.pending,
                    ),
                    Deadline(
                        user_id=1,
                        title="Done deadline",
                        due_date=date(2026, 8, 3),
                        status=DeadlineStatus.done,
                    ),
                ]
            )
            db.commit()

            result = list_reminder_candidates(db, 1, local_day, (2, 1, 0, -1, -3, -7))
            self.assertEqual(57, len(result))
            self.assertIn("Process child", [item.title for item in result])
            self.assertIn("External deadline", [item.title for item in result])
            self.assertNotIn("Process container", [item.title for item in result])
            self.assertNotIn("Done", [item.title for item in result])

    def test_timezone_0900_and_dst_boundaries(self):
        before = local_run_context(
            datetime(2026, 8, 3, 0, 59, tzinfo=timezone.utc), "Asia/Shanghai"
        )
        at_time = local_run_context(
            datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc), "Asia/Shanghai"
        )
        self.assertFalse(before.due)
        self.assertTrue(at_time.due)
        self.assertEqual(date(2026, 8, 3), at_time.local_date)

        dst = local_run_context(
            datetime(2026, 3, 8, 13, 0, tzinfo=timezone.utc), "America/New_York"
        )
        self.assertTrue(dst.due)
        self.assertEqual(9, dst.local_now.hour)

    def test_claim_is_idempotent_and_final_snapshot_rechecks_state(self):
        with self.SessionLocal() as db:
            db.add_all(
                [
                    AppTask(
                        user_id=1,
                        title="Keep",
                        status="todo",
                        deadline=date(2026, 8, 5),
                    ),
                    AppTask(
                        user_id=1,
                        title="Complete later",
                        status="todo",
                        deadline=date(2026, 8, 5),
                    ),
                    AppTask(
                        user_id=1,
                        title="Delete later",
                        status="todo",
                        deadline=date(2026, 8, 5),
                    ),
                    Deadline(
                        user_id=1,
                        title="Reschedule later",
                        due_date=date(2026, 8, 5),
                        status=DeadlineStatus.pending,
                    ),
                ]
            )
            db.commit()
            prefs = resolve_preferences(db, 1)
            now = datetime(2026, 8, 3, 1, 1, tzinfo=timezone.utc)
            first = claim_daily_digest(db, 1, now, prefs)
            second = claim_daily_digest(db, 1, now, prefs)
            self.assertEqual(first.digest.id, second.digest.id)
            self.assertEqual(4, db.query(ReminderOccurrence).count())
            self.assertEqual(1, db.query(ReminderDigest).count())

            complete = db.query(AppTask).filter(AppTask.title == "Complete later").one()
            complete.status = "done"
            deleted = db.query(AppTask).filter(AppTask.title == "Delete later").one()
            db.delete(deleted)
            moved = db.query(Deadline).filter(Deadline.title == "Reschedule later").one()
            moved.due_date = date(2026, 8, 10)
            db.commit()

            snapshots = finalize_digest_snapshot(db, first)
            self.assertEqual(["Keep"], [item["title"] for item in snapshots])
            cancelled = (
                db.query(ReminderOccurrence)
                .filter(ReminderOccurrence.state == ReminderOccurrenceState.cancelled)
                .count()
            )
            self.assertEqual(3, cancelled)

            third = claim_daily_digest(db, 1, now, prefs)
            self.assertEqual([], third.candidates)
            self.assertEqual(4, db.query(ReminderOccurrence).count())

            rescheduled = claim_daily_digest(
                db,
                1,
                datetime(2026, 8, 8, 1, 1, tzinfo=timezone.utc),
                prefs,
            )
            self.assertIn("Reschedule later", [item.title for item in rescheduled.candidates])
            self.assertTrue(
                any(
                    item.title == "Reschedule later" and item.due_date == date(2026, 8, 10)
                    for item in rescheduled.candidates
                )
            )

    def test_six_cadence_points_only(self):
        local_day = date(2026, 8, 3)
        with self.SessionLocal() as db:
            for offset in (2, 1, 0, -1, -2, -3, -7, -8):
                db.add(
                    AppTask(
                        user_id=1,
                        title=f"offset-{offset}",
                        status="overdue" if offset < 0 else "todo",
                        deadline=date.fromordinal(local_day.toordinal() + offset),
                    )
                )
            db.commit()
            result = list_reminder_candidates(db, 1, local_day, (2, 1, 0, -1, -3, -7))
            self.assertEqual({2, 1, 0, -1, -3, -7}, {item.cadence_offset for item in result})

    def test_two_sessions_cannot_duplicate_claims(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reminder-race.sqlite"
            engine = create_engine(
                f"sqlite:///{path}",
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            sessions = sessionmaker(bind=engine, autoflush=False)
            Base.metadata.create_all(engine)
            with sessions() as db:
                db.add(User(username="race", email="race@example.com", password="x"))
                db.commit()
                seed_builtin_role_cards(db)
                db.add(
                    AppTask(
                        user_id=1,
                        title="Race item",
                        status="todo",
                        deadline=date(2026, 8, 5),
                    )
                )
                db.commit()

            barrier = threading.Barrier(2)
            results = []
            errors = []

            def run_claim():
                try:
                    with sessions() as db:
                        prefs = resolve_preferences(db, 1)
                        barrier.wait(timeout=5)
                        claimed = claim_daily_digest(
                            db,
                            1,
                            datetime(2026, 8, 3, 1, 1, tzinfo=timezone.utc),
                            prefs,
                        )
                        results.append(claimed.digest.id)
                except Exception as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            threads = [threading.Thread(target=run_claim) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertEqual([], errors)
            self.assertEqual(2, len(results))
            self.assertEqual(1, len(set(results)))
            with sessions() as db:
                self.assertEqual(1, db.query(ReminderDigest).count())
                self.assertEqual(1, db.query(ReminderOccurrence).count())
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
