import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models.reminder import (  # noqa: E402
    ReminderDeliveryStatus,
    TaskReminderDelivery,
    TaskReminderNotification,
    TaskReminderState,
)
from models.task_new import Task, TaskType  # noqa: E402
from models.user import User  # noqa: E402
from services.reminder_agent import GeneratedReminderContent  # noqa: E402
from services.reminder_orchestrator import ReminderOrchestrator  # noqa: E402
from services.reminder_preferences import (  # noqa: E402
    DEFAULT_DAILY_DISPATCH_TIME,
    DEFAULT_TASK_REMINDER_OFFSETS_MINUTES,
    normalize_daily_dispatch_time,
    resolve_preferences,
    update_preferences,
)
from services.reminder_scheduler import (  # noqa: E402
    claim_due_task_relative_notifications,
    local_run_context,
    revalidate_task_relative_notification,
)
from services.reminder_seeds import seed_builtin_role_cards  # noqa: E402


class FakeAgent:
    async def generate(self, db, **kwargs):
        return GeneratedReminderContent(
            subject="daily",
            framing="daily",
            body="daily body",
            mode="template",
            attempts=1,
        )


class FakeTransport:
    def __init__(self):
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)
        return f"provider-{len(self.messages)}"


class ConfigurableTimedReminderTests(unittest.IsolatedAsyncioTestCase):
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
            db.add(User(username="owner", email="owner@example.com", password="x"))
            db.commit()
            seed_builtin_role_cards(db)

    def test_defaults_and_strict_dispatch_time(self):
        self.assertEqual("09:00", DEFAULT_DAILY_DISPATCH_TIME)
        self.assertEqual((5, 1440), DEFAULT_TASK_REMINDER_OFFSETS_MINUTES)
        self.assertEqual("00:00", normalize_daily_dispatch_time("00:00"))
        self.assertEqual("23:59", normalize_daily_dispatch_time("23:59"))
        for value in ("9:00", "24:00", "12:60", "12:00:00", "bad"):
            with self.assertRaises(ValueError):
                normalize_daily_dispatch_time(value)
        with self.SessionLocal() as db:
            prefs = resolve_preferences(db, 1)
            self.assertEqual("09:00", prefs.daily_dispatch_time)
            self.assertEqual((5, 1440), prefs.default_task_reminder_offsets_minutes)
            update_preferences(db, 1, daily_dispatch_time="18:30")
            self.assertEqual("18:30", resolve_preferences(db, 1).daily_dispatch_time)

    def test_custom_daily_time_is_timezone_aware(self):
        before = local_run_context(
            datetime(2026, 8, 3, 10, 29, tzinfo=timezone.utc),
            "Asia/Shanghai",
            "18:30",
        )
        after = local_run_context(
            datetime(2026, 8, 3, 10, 30, tzinfo=timezone.utc),
            "Asia/Shanghai",
            "18:30",
        )
        self.assertFalse(before.due)
        self.assertTrue(after.due)

    async def test_relative_defaults_are_independent_and_idempotent(self):
        now = datetime(2026, 8, 3, 1, 38, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            db.add_all(
                [
                    Task(
                        user_id=1,
                        task_type=TaskType.todo,
                        title="five minutes",
                        status="todo",
                        deadline=datetime(2026, 8, 3, 9, 43),
                    ),
                    Task(
                        user_id=1,
                        task_type=TaskType.todo,
                        title="one day",
                        status="todo",
                        deadline=datetime(2026, 8, 4, 9, 38),
                    ),
                    Task(
                        user_id=1,
                        task_type=TaskType.todo,
                        title="opt out",
                        status="todo",
                        deadline=datetime(2026, 8, 3, 9, 43),
                        reminder_offsets_minutes=[],
                    ),
                ]
            )
            db.commit()
            prefs = resolve_preferences(db, 1)
            claimed = claim_due_task_relative_notifications(
                db, user_id=1, preferences=prefs, now_utc=now
            )
            self.assertEqual(2, len(claimed))
            self.assertEqual({5, 1440}, {row.offset_minutes for row in claimed})
            self.assertEqual(2, len(claim_due_task_relative_notifications(
                db, user_id=1, preferences=prefs, now_utc=now
            )))

            service = ReminderOrchestrator(agent=FakeAgent(), email_transport=FakeTransport())
            # The full worker run is also eligible at 09:01 local and delivers
            # the same relative claims without creating duplicates.
            transport = service.registry.get("email").transport
            await service.run(db, now_utc=now)
            self.assertEqual(2, db.query(TaskReminderNotification).count())
            self.assertEqual(4, db.query(TaskReminderDelivery).count())
            self.assertEqual(3, len(transport.messages))  # 2 relative + 1 daily digest
            self.assertTrue(
                all(
                    row.status in {ReminderDeliveryStatus.delivered, ReminderDeliveryStatus.skipped}
                    for row in db.query(TaskReminderDelivery).all()
                )
            )

    def test_completion_and_reschedule_cancel_claim(self):
        now = datetime(2026, 8, 3, 1, 1, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                title="reschedule",
                status="todo",
                deadline=datetime(2026, 8, 3, 9, 6),
            )
            db.add(task)
            db.commit()
            prefs = resolve_preferences(db, 1)
            notification = claim_due_task_relative_notifications(
                db, user_id=1, preferences=prefs, now_utc=now
            )[0]
            task.deadline = task.deadline + timedelta(hours=1)
            db.commit()
            self.assertFalse(revalidate_task_relative_notification(db, notification))
            self.assertEqual(TaskReminderState.cancelled, notification.state)


if __name__ == "__main__":
    unittest.main()
