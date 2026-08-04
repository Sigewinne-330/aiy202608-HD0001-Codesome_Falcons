import asyncio
import os
import sys
import threading
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base, SessionLocal, auto_sync_tables, engine  # noqa: E402
import models  # noqa: E402,F401
from models.chat_message_new import ChatMessage  # noqa: E402
from models.reminder import (  # noqa: E402
    ReminderDelivery,
    ReminderDeliveryStatus,
    ReminderDigest,
    ReminderGenerationMode,
    ReminderOccurrence,
    ReminderPreference,
    ReminderRoleCard,
)
from models.task_new import Task as AppTask  # noqa: E402
from models.user import User  # noqa: E402
from services.reminder_agent import GeneratedReminderContent  # noqa: E402
from services.reminder_orchestrator import ReminderOrchestrator  # noqa: E402
from services.reminder_preferences import ensure_preferences  # noqa: E402
from services.reminder_scheduler import local_run_context  # noqa: E402
from services.reminder_seeds import (  # noqa: E402
    BUILTIN_ROLE_CARDS,
    seed_builtin_role_cards,
)


RUN_MYSQL = os.getenv("RUN_MYSQL_REMINDER_TESTS") == "1"


class SlowFakeAgent:
    async def generate(self, db, **kwargs):
        await asyncio.sleep(0.12)
        return GeneratedReminderContent(
            subject="受控并发提醒",
            framing="这些项目已进入截止窗口，请及时安排。",
            body="这些项目已进入截止窗口，请及时安排。\n\n- 并发测试任务\n\nhttp://localhost:5173/chat",
            mode=ReminderGenerationMode.llm,
            attempts=1,
        )


class SlowFakeTransport:
    def __init__(self):
        self._lock = threading.Lock()
        self.message_count = 0

    def send_message(self, message):
        with self._lock:
            self.message_count += 1
            sequence = self.message_count
        time.sleep(0.12)
        return f"mysql-fake-{sequence}"


@unittest.skipUnless(RUN_MYSQL, "set RUN_MYSQL_REMINDER_TESTS=1 for actual MySQL gate")
class ReminderMySQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.dialect.name != "mysql":
            raise unittest.SkipTest("configured database is not MySQL")
        Base.metadata.create_all(bind=engine)
        auto_sync_tables(engine, Base)

    def setUp(self):
        suffix = uuid4().hex[:12]
        self.username = f"reminder_mysql_{suffix}"
        self.email = f"reminder_mysql_{suffix}@example.com"
        with SessionLocal() as db:
            first = seed_builtin_role_cards(db)
            second = seed_builtin_role_cards(db)
            self.assertEqual(
                [card.slug for card in first], [card.slug for card in second]
            )
            user = User(
                username=self.username,
                email=self.email,
                password="integration-only",
            )
            db.add(user)
            db.flush()
            self.user_id = user.id
            db.add(
                AppTask(
                    user_id=user.id,
                    title="MySQL concurrency fixture",
                    status="todo",
                    deadline=datetime(2026, 8, 5),
                )
            )
            db.commit()

    def tearDown(self):
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == self.user_id).first()
            if user:
                db.delete(user)
                db.commit()

    def test_schema_seed_timezone_and_two_worker_idempotency(self):
        schema = inspect(engine)
        required_tables = {
            "reminder_preferences",
            "reminder_role_cards",
            "reminder_occurrences",
            "reminder_digests",
            "reminder_deliveries",
            "llm_usage_records",
        }
        self.assertTrue(required_tables.issubset(set(schema.get_table_names())))
        delivery_columns = {
            column["name"] for column in schema.get_columns("reminder_deliveries")
        }
        self.assertTrue(
            {"attempt_token", "attempt_started_at"}.issubset(delivery_columns)
        )
        self.assertIn(
            "scope",
            {
                column["name"]
                for column in schema.get_columns("reminder_role_cards")
            },
        )
        expected_slugs = {definition["slug"] for definition in BUILTIN_ROLE_CARDS}
        with SessionLocal() as db:
            self.assertEqual(
                expected_slugs,
                {
                    row.slug
                    for row in db.query(ReminderRoleCard)
                    .filter(ReminderRoleCard.slug.in_(expected_slugs))
                    .all()
                },
            )
        context = local_run_context(
            datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc), "Asia/Shanghai"
        )
        self.assertTrue(context.due)
        self.assertEqual(date(2026, 8, 3), context.local_date)

        preference_barrier = threading.Barrier(2)
        preference_ids = []
        preference_errors = []

        def create_preference():
            try:
                with SessionLocal() as db:
                    preference_barrier.wait(timeout=5)
                    preference_ids.append(ensure_preferences(db, self.user_id).id)
            except Exception as exc:  # pragma: no cover - asserted below
                preference_errors.append(type(exc).__name__)

        preference_workers = [
            threading.Thread(target=create_preference) for _ in range(2)
        ]
        for thread in preference_workers:
            thread.start()
        for thread in preference_workers:
            thread.join(timeout=10)
        self.assertEqual([], preference_errors)
        self.assertEqual(1, len(set(preference_ids)))
        with SessionLocal() as db:
            self.assertEqual(
                1,
                db.query(ReminderPreference)
                .filter(ReminderPreference.user_id == self.user_id)
                .count(),
            )

        barrier = threading.Barrier(2)
        transport = SlowFakeTransport()
        agent = SlowFakeAgent()
        errors = []

        def worker():
            try:
                with SessionLocal() as db:
                    barrier.wait(timeout=5)
                    asyncio.run(
                        ReminderOrchestrator(
                            agent=agent, email_transport=transport
                        ).run(
                            db,
                            now_utc=datetime(
                                2026, 8, 3, 1, 0, tzinfo=timezone.utc
                            ),
                            only_user_id=self.user_id,
                        )
                    )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(type(exc).__name__)

        workers = [threading.Thread(target=worker) for _ in range(2)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(timeout=15)

        self.assertEqual([], errors)
        self.assertTrue(all(not thread.is_alive() for thread in workers))
        with SessionLocal() as db:
            self.assertEqual(
                1,
                db.query(ReminderDigest)
                .filter(ReminderDigest.user_id == self.user_id)
                .count(),
            )
            self.assertEqual(
                1,
                db.query(ReminderOccurrence)
                .filter(ReminderOccurrence.user_id == self.user_id)
                .count(),
            )
            self.assertEqual(
                1,
                db.query(ChatMessage)
                .filter(ChatMessage.user_id == self.user_id)
                .count(),
            )
            deliveries = (
                db.query(ReminderDelivery)
                .join(ReminderDigest)
                .filter(ReminderDigest.user_id == self.user_id)
                .all()
            )
            self.assertEqual({"chat", "email"}, {row.channel for row in deliveries})
            self.assertTrue(
                all(row.status == ReminderDeliveryStatus.delivered for row in deliveries)
            )
            digest_ids = [row.id for row in db.query(ReminderDigest).filter_by(user_id=self.user_id)]
        self.assertEqual(1, transport.message_count)

        with SessionLocal() as db:
            db.delete(db.query(User).filter(User.id == self.user_id).one())
            db.commit()
            self.assertEqual(
                0,
                db.query(ReminderPreference)
                .filter(ReminderPreference.user_id == self.user_id)
                .count(),
            )
            self.assertEqual(
                0,
                db.query(ReminderDigest)
                .filter(ReminderDigest.user_id == self.user_id)
                .count(),
            )
            self.assertEqual(
                0,
                db.query(ReminderDelivery)
                .filter(ReminderDelivery.digest_id.in_(digest_ids))
                .count(),
            )


if __name__ == "__main__":
    unittest.main()
