import asyncio
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import settings  # noqa: E402
from database import Base, get_db  # noqa: E402
import models  # noqa: E402,F401
from models.chat_message_new import ChatMessage  # noqa: E402
from models.reminder import (  # noqa: E402
    ReminderDelivery,
    ReminderDigest,
    ReminderGenerationMode,
)
from models.task_new import Task  # noqa: E402
from models.user import User  # noqa: E402
from routers.reminders import (  # noqa: E402
    get_current_user,
    get_reminder_orchestrator,
    router,
)
from services.email_service import EmailDeliveryError  # noqa: E402
from services.reminder_agent import GeneratedReminderContent  # noqa: E402
from services.reminder_channels import ChannelResult  # noqa: E402
from services.reminder_orchestrator import ReminderOrchestrator  # noqa: E402
from services.reminder_preferences import ensure_preferences  # noqa: E402
from services.reminder_seeds import seed_builtin_role_cards  # noqa: E402


class FakeReminderAgent:
    def __init__(self):
        self.calls = []

    async def generate(self, db, **kwargs):
        self.calls.append(kwargs)
        return GeneratedReminderContent(
            subject="Demo reminder",
            framing="This is a demo reminder.",
            body="This is a demo reminder.\n\nContinue in AI chat: http://localhost:5173/chat",
            mode=ReminderGenerationMode.template,
            attempts=0,
        )


class FakeTransport:
    def __init__(self, failure=False):
        self.failure = failure
        self.calls = []

    def send_message(self, message):
        self.calls.append(message)
        if self.failure:
            raise EmailDeliveryError(
                "fake smtp failure", code="smtp_auth_failed", retryable=False
            )
        return "demo-message-id"


class DemoReminderServiceTests(unittest.TestCase):
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
            db.add(User(username="demo", email="demo@example.com", password="x"))
            db.commit()
            seed_builtin_role_cards(db)
        self.agent = FakeReminderAgent()
        self.transport = FakeTransport()
        self.user_id = 1

    def test_demo_delivery_reuses_context_without_formal_records(self):
        with self.SessionLocal() as db:
            result = asyncio.run(
                ReminderOrchestrator(
                    agent=self.agent, email_transport=self.transport
                ).send_demo(db, user=db.query(User).one())
            )

            self.assertEqual({"chat", "email"}, set(result["outcomes"]))
            self.assertEqual("delivered", result["outcomes"]["chat"].status)
            self.assertEqual("delivered", result["outcomes"]["email"].status)
            self.assertEqual(1, len(self.agent.calls))
            self.assertEqual("zh-CN", self.agent.calls[0]["language"])
            self.assertEqual("friendly-warm-guy", self.agent.calls[0]["role_card"].slug)
            self.assertEqual(0, db.query(Task).count())
            self.assertEqual(0, db.query(ReminderDigest).count())
            self.assertEqual(0, db.query(ReminderDelivery).count())
            message = db.query(ChatMessage).one()
            self.assertEqual("demo_reminder", message.extra["source"])

    def test_repeated_demo_calls_do_not_leave_digest_or_delivery_rows(self):
        with self.SessionLocal() as db:
            user = db.query(User).one()
            orchestrator = ReminderOrchestrator(
                agent=self.agent, email_transport=self.transport
            )
            asyncio.run(orchestrator.send_demo(db, user=user))
            asyncio.run(orchestrator.send_demo(db, user=user))
            self.assertEqual(2, db.query(ChatMessage).count())
            self.assertEqual(0, db.query(ReminderDigest).count())
            self.assertEqual(0, db.query(ReminderDelivery).count())

    def test_disabled_email_is_reported_without_sending(self):
        with self.SessionLocal() as db:
            ensure_preferences(db, self.user_id)
            preference = db.query(models.ReminderPreference).one()
            preference.email_enabled = False
            db.commit()
            result = asyncio.run(
                ReminderOrchestrator(
                    agent=self.agent, email_transport=self.transport
                ).send_demo(db, user=db.query(User).one())
            )
            self.assertEqual("delivered", result["outcomes"]["chat"].status)
            self.assertEqual("skipped", result["outcomes"]["email"].status)
            self.assertEqual(0, len(self.transport.calls))

    def test_email_failure_does_not_remove_chat_message(self):
        with self.SessionLocal() as db:
            result = asyncio.run(
                ReminderOrchestrator(
                    agent=self.agent, email_transport=FakeTransport(failure=True)
                ).send_demo(db, user=db.query(User).one())
            )
            self.assertEqual("delivered", result["outcomes"]["chat"].status)
            self.assertEqual("failed", result["outcomes"]["email"].status)
            self.assertEqual("smtp_auth_failed", result["outcomes"]["email"].error_code)
            self.assertEqual(1, db.query(ChatMessage).count())


class DemoReminderApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_flag = settings.DEMO_REMINDER_ENABLED
        self.fake_orchestrator = type(
            "FakeOrchestrator",
            (),
            {
                "send_demo": lambda self, db, *, user: asyncio.sleep(0, result={
                    "subject": "Demo",
                    "outcomes": {
                        "chat": ChannelResult(status="delivered"),
                        "email": ChannelResult(status="skipped", error_code="channel_disabled"),
                    },
                })
            },
        )()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)
        with self.SessionLocal() as db:
            db.add(User(username="owner", email="owner@example.com", password="x"))
            db.commit()
        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.SessionLocal() as db:
                yield db

        def owner():
            with self.SessionLocal() as db:
                return db.query(User).one()

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[get_current_user] = owner
        self.app.dependency_overrides[get_reminder_orchestrator] = (
            lambda: self.fake_orchestrator
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        settings.DEMO_REMINDER_ENABLED = self.previous_flag
        self.engine.dispose()

    def test_disabled_flag_returns_not_found(self):
        settings.DEMO_REMINDER_ENABLED = False
        self.assertEqual(404, self.client.post("/api/reminders/demo-send").status_code)

    def test_enabled_flag_returns_sanitized_channel_outcomes(self):
        settings.DEMO_REMINDER_ENABLED = True
        response = self.client.post("/api/reminders/demo-send")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("delivered", response.json()["chat"]["status"])
        self.assertEqual("channel_disabled", response.json()["email"]["error_code"])


if __name__ == "__main__":
    unittest.main()
