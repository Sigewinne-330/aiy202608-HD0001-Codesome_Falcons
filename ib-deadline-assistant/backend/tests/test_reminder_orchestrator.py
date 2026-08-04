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
import models  # noqa: E402,F401
from models.chat_message_new import ChatMessage  # noqa: E402
from models.reminder import (  # noqa: E402
    ReminderDelivery,
    ReminderDeliveryStatus,
    ReminderDigest,
    ReminderDigestState,
    ReminderGenerationMode,
    ReminderOccurrence,
)
from models.task_new import Task as AppTask  # noqa: E402
from models.user import User  # noqa: E402
from services.email_service import EmailDeliveryError  # noqa: E402
from services.reminder_agent import GeneratedReminderContent  # noqa: E402
from services.reminder_orchestrator import ReminderOrchestrator  # noqa: E402
from services.reminder_seeds import seed_builtin_role_cards  # noqa: E402


class FakeAgent:
    def __init__(self, mutation=None):
        self.calls = []
        self.mutation = mutation

    async def generate(self, db, **kwargs):
        self.calls.append(kwargs)
        if self.mutation:
            self.mutation(db)
        return GeneratedReminderContent(
            subject="清晰的提醒标题",
            framing="这些项目已经进入截止窗口，请及时安排。",
            body=(
                "这些项目已经进入截止窗口，请及时安排。\n\n"
                + "\n".join(f"- {item['title']}" for item in kwargs["item_snapshots"])
                + "\n\nhttp://localhost:5173/chat"
            ),
            mode=ReminderGenerationMode.llm,
            attempts=1,
        )


class FakeTransport:
    def __init__(self, failures=None):
        self.failures = list(failures or [])
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)
        if self.failures:
            failure = self.failures.pop(0)
            if failure:
                raise failure
        return f"provider-{len(self.messages)}"


class ReminderOrchestratorTests(unittest.IsolatedAsyncioTestCase):
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
            db.add(User(username="owner", email="owner@example.com", password_hash="x"))
            db.commit()
            seed_builtin_role_cards(db)
            db.add(
                AppTask(
                    user_id=1,
                    title="Due soon",
                    status="todo",
                    deadline=datetime(2026, 8, 5),
                )
            )
            db.commit()

    async def test_full_fake_delivery_and_rerun_are_idempotent(self):
        agent = FakeAgent()
        transport = FakeTransport()
        service = ReminderOrchestrator(agent=agent, email_transport=transport)
        now = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            first = await service.run(db, now_utc=now)
            second = await service.run(db, now_utc=now + timedelta(minutes=1))
            self.assertEqual(1, first.generated_digests)
            self.assertEqual(0, second.generated_digests)
            self.assertEqual(1, len(agent.calls))
            self.assertEqual(1, len(transport.messages))
            self.assertEqual(1, db.query(ReminderDigest).count())
            self.assertEqual(1, db.query(ReminderOccurrence).count())
            self.assertEqual(1, db.query(ChatMessage).count())
            self.assertEqual(2, db.query(ReminderDelivery).count())
            self.assertTrue(
                all(
                    row.status == ReminderDeliveryStatus.delivered
                    for row in db.query(ReminderDelivery).all()
                )
            )

    async def test_dry_run_has_no_persistent_or_external_side_effects(self):
        agent = FakeAgent()
        transport = FakeTransport()
        service = ReminderOrchestrator(agent=agent, email_transport=transport)
        with self.SessionLocal() as db:
            summary = await service.run(
                db,
                now_utc=datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc),
                deliver=False,
            )
            self.assertTrue(summary.dry_run)
            self.assertEqual(1, summary.candidate_items)
            self.assertEqual(0, db.query(ReminderDigest).count())
            self.assertEqual([], agent.calls)
            self.assertEqual([], transport.messages)

    async def test_final_recheck_cancels_item_completed_during_generation(self):
        def complete_task(db):
            task = db.query(AppTask).one()
            task.status = "done"
            db.commit()

        agent = FakeAgent(mutation=complete_task)
        transport = FakeTransport()
        service = ReminderOrchestrator(agent=agent, email_transport=transport)
        with self.SessionLocal() as db:
            await service.run(
                db, now_utc=datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
            )
            digest = db.query(ReminderDigest).one()
            self.assertEqual(ReminderDigestState.cancelled, digest.state)
            self.assertEqual([], transport.messages)
            self.assertEqual(0, db.query(ChatMessage).count())
            self.assertEqual(0, db.query(ReminderDelivery).count())

    async def test_due_delivery_retry_runs_without_regeneration(self):
        failure = EmailDeliveryError(
            "temporary", code="smtp_transient_failure", retryable=True
        )
        agent = FakeAgent()
        transport = FakeTransport([failure, None])
        service = ReminderOrchestrator(agent=agent, email_transport=transport)
        start = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            await service.run(db, now_utc=start)
            email = db.query(ReminderDelivery).filter_by(channel="email").one()
            self.assertEqual(ReminderDeliveryStatus.retryable, email.status)
            await service.run(db, now_utc=start + timedelta(minutes=2))
            db.refresh(email)
            self.assertEqual(ReminderDeliveryStatus.delivered, email.status)
            self.assertEqual(2, len(transport.messages))
            self.assertEqual(1, len(agent.calls))


if __name__ == "__main__":
    unittest.main()
