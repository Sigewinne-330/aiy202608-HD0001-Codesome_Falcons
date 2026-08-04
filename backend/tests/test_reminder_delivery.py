import sys
import unittest
from datetime import date, datetime, timedelta
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
)
from models.user import User  # noqa: E402
from schemas.chat import ChatResponse  # noqa: E402
from services.email_service import EmailDeliveryError  # noqa: E402
from services.reminder_channels import (  # noqa: E402
    ChannelResult,
    ChannelRegistry,
    ChatReminderChannel,
    EmailReminderChannel,
)
from services.reminder_delivery import (  # noqa: E402
    deliver_digest_channels,
    deliver_one_channel,
)
from services.reminder_preferences import resolve_preferences  # noqa: E402
from services.reminder_seeds import seed_builtin_role_cards  # noqa: E402


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
        return f"fake-{len(self.messages)}"


class FailingChatChannel:
    name = "chat"
    ambiguous_external_side_effect = False

    def deliver(self, db, envelope):
        raise RuntimeError("simulated persistence failure")


class FakeConnectorChannel:
    name = "connector"
    ambiguous_external_side_effect = False

    def deliver(self, db, envelope):
        return ChannelResult(status="delivered", provider_message_id="connector-1")


class ReminderDeliveryTests(unittest.TestCase):
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
            user = User(username="owner", email="owner@example.com", password="x")
            db.add(user)
            db.commit()
            cards = seed_builtin_role_cards(db)
            db.add(
                ReminderDigest(
                    user_id=user.id,
                    local_date=date(2026, 8, 3),
                    timezone="Asia/Shanghai",
                    language="zh-CN",
                    role_card_id=cards[0].id,
                    subject="清晰的日程提醒",
                    framing_text="这些项目需要关注。",
                    item_snapshot=[
                        {
                            "item_type": "task",
                            "item_id": 3,
                            "title": "Task",
                            "due_date": "2026-08-05",
                        }
                    ],
                    body_text="这些项目需要关注。\n\n- Task\n\nhttps://example.test/chat",
                    chat_url="https://example.test/chat",
                    generation_mode=ReminderGenerationMode.template,
                    state=ReminderDigestState.ready,
                )
            )
            db.commit()

    def test_channels_succeed_independently_and_are_idempotent(self):
        transport = FakeTransport()
        registry = ChannelRegistry(
            [ChatReminderChannel(), EmailReminderChannel(transport)]
        )
        with self.SessionLocal() as db:
            user = db.query(User).one()
            digest = db.query(ReminderDigest).one()
            prefs = resolve_preferences(db, user.id)
            first = deliver_digest_channels(
                db, digest=digest, user=user, preferences=prefs, registry=registry
            )
            second = deliver_digest_channels(
                db, digest=digest, user=user, preferences=prefs, registry=registry
            )
            self.assertEqual(ReminderDeliveryStatus.delivered, first["chat"].status)
            self.assertEqual(ReminderDeliveryStatus.delivered, first["email"].status)
            self.assertEqual(ReminderDeliveryStatus.delivered, second["chat"].status)
            self.assertEqual(1, len(transport.messages))
            self.assertEqual(1, db.query(ChatMessage).count())
            self.assertEqual(2, db.query(ReminderDelivery).count())

            message = db.query(ChatMessage).one()
            self.assertEqual("reminder", message.extra["source"])
            self.assertEqual(digest.id, message.extra["digest_id"])
            response = ChatResponse.model_validate(message).model_dump()
            self.assertEqual("reminder", response["metadata"]["source"])

    def test_email_retries_three_times_while_chat_succeeds(self):
        failure = EmailDeliveryError(
            "temporary", code="smtp_transient_failure", retryable=True
        )
        transport = FakeTransport([failure, failure, failure])
        registry = ChannelRegistry(
            [ChatReminderChannel(), EmailReminderChannel(transport)]
        )
        start = datetime(2026, 8, 3, 1, 0)
        with self.SessionLocal() as db:
            user = db.query(User).one()
            digest = db.query(ReminderDigest).one()
            prefs = resolve_preferences(db, user.id)
            first = deliver_digest_channels(
                db,
                digest=digest,
                user=user,
                preferences=prefs,
                registry=registry,
                now=start,
            )
            self.assertEqual(ReminderDeliveryStatus.delivered, first["chat"].status)
            self.assertEqual(ReminderDeliveryStatus.retryable, first["email"].status)

            deliver_one_channel(
                db,
                digest=digest,
                user=user,
                channel_name="email",
                enabled=True,
                registry=registry,
                now=start + timedelta(minutes=2),
            )
            final = deliver_one_channel(
                db,
                digest=digest,
                user=user,
                channel_name="email",
                enabled=True,
                registry=registry,
                now=start + timedelta(minutes=5),
            )
            self.assertEqual(ReminderDeliveryStatus.failed, final.status)
            self.assertEqual(3, final.attempt_count)
            again = deliver_one_channel(
                db,
                digest=digest,
                user=user,
                channel_name="email",
                enabled=True,
                registry=registry,
                now=start + timedelta(days=1),
            )
            self.assertEqual(3, again.attempt_count)
            self.assertEqual(3, len(transport.messages))
            self.assertEqual(1, db.query(ChatMessage).count())

    def test_permanent_failure_and_disabled_channel_do_not_retry(self):
        transport = FakeTransport(
            [EmailDeliveryError("auth", code="smtp_auth_failed", retryable=False)]
        )
        registry = ChannelRegistry(
            [ChatReminderChannel(), EmailReminderChannel(transport)]
        )
        with self.SessionLocal() as db:
            user = db.query(User).one()
            digest = db.query(ReminderDigest).one()
            email = deliver_one_channel(
                db,
                digest=digest,
                user=user,
                channel_name="email",
                enabled=True,
                registry=registry,
            )
            chat = deliver_one_channel(
                db,
                digest=digest,
                user=user,
                channel_name="chat",
                enabled=False,
                registry=registry,
            )
            self.assertEqual(ReminderDeliveryStatus.failed, email.status)
            self.assertEqual("smtp_auth_failed", email.last_error_code)
            self.assertEqual(1, email.attempt_count)
            self.assertEqual(ReminderDeliveryStatus.skipped, chat.status)
            self.assertEqual(0, db.query(ChatMessage).count())

    def test_abandoned_smtp_attempt_is_not_resent(self):
        transport = FakeTransport()
        registry = ChannelRegistry(
            [ChatReminderChannel(), EmailReminderChannel(transport)]
        )
        with self.SessionLocal() as db:
            user = db.query(User).one()
            digest = db.query(ReminderDigest).one()
            db.add(
                ReminderDelivery(
                    digest_id=digest.id,
                    channel="email",
                    status=ReminderDeliveryStatus.attempting,
                    attempt_count=1,
                )
            )
            db.commit()
            result = deliver_one_channel(
                db,
                digest=digest,
                user=user,
                channel_name="email",
                enabled=True,
                registry=registry,
            )
            self.assertEqual(ReminderDeliveryStatus.failed, result.status)
            self.assertEqual("delivery_outcome_unknown", result.last_error_code)
            self.assertEqual([], transport.messages)

    def test_fresh_attempt_leases_are_not_executed_by_another_worker(self):
        transport = FakeTransport()
        registry = ChannelRegistry(
            [ChatReminderChannel(), EmailReminderChannel(transport)]
        )
        current = datetime(2026, 8, 3, 1, 0)
        with self.SessionLocal() as db:
            user = db.query(User).one()
            digest = db.query(ReminderDigest).one()
            db.add_all(
                [
                    ReminderDelivery(
                        digest_id=digest.id,
                        channel=channel,
                        status=ReminderDeliveryStatus.attempting,
                        attempt_count=1,
                        attempt_token=f"lease-{channel}",
                        attempt_started_at=current,
                    )
                    for channel in ("chat", "email")
                ]
            )
            db.commit()
            for channel in ("chat", "email"):
                result = deliver_one_channel(
                    db,
                    digest=digest,
                    user=user,
                    channel_name=channel,
                    enabled=True,
                    registry=registry,
                    now=current + timedelta(minutes=1),
                )
                self.assertEqual(ReminderDeliveryStatus.attempting, result.status)
            self.assertEqual([], transport.messages)
            self.assertEqual(0, db.query(ChatMessage).count())

    def test_channel_failure_is_isolated_and_connector_is_extensible(self):
        transport = FakeTransport()
        registry = ChannelRegistry(
            [FailingChatChannel(), EmailReminderChannel(transport), FakeConnectorChannel()]
        )
        with self.SessionLocal() as db:
            user = db.query(User).one()
            digest = db.query(ReminderDigest).one()
            prefs = resolve_preferences(db, user.id)
            outcomes = deliver_digest_channels(
                db, digest=digest, user=user, preferences=prefs, registry=registry
            )
            self.assertEqual(ReminderDeliveryStatus.retryable, outcomes["chat"].status)
            self.assertEqual(ReminderDeliveryStatus.delivered, outcomes["email"].status)
            self.assertEqual(1, len(transport.messages))

            connector = deliver_one_channel(
                db,
                digest=digest,
                user=user,
                channel_name="connector",
                enabled=True,
                registry=registry,
            )
            self.assertEqual(ReminderDeliveryStatus.delivered, connector.status)

    def test_clearing_visible_chat_keeps_delivery_audit_and_prevents_redelivery(self):
        transport = FakeTransport()
        registry = ChannelRegistry(
            [ChatReminderChannel(), EmailReminderChannel(transport)]
        )
        with self.SessionLocal() as db:
            user = db.query(User).one()
            digest = db.query(ReminderDigest).one()
            prefs = resolve_preferences(db, user.id)
            deliver_digest_channels(
                db, digest=digest, user=user, preferences=prefs, registry=registry
            )
            db.query(ChatMessage).filter(ChatMessage.user_id == user.id).delete()
            db.commit()
            deliver_digest_channels(
                db, digest=digest, user=user, preferences=prefs, registry=registry
            )
            self.assertEqual(0, db.query(ChatMessage).count())
            self.assertEqual(2, db.query(ReminderDelivery).count())
            self.assertEqual(1, len(transport.messages))


if __name__ == "__main__":
    unittest.main()
