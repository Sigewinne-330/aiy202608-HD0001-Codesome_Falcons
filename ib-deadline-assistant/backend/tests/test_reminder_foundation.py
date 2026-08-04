import sys
import unittest
from datetime import date
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models.reminder import (  # noqa: E402
    LLMUsageRecord,
    ReminderDelivery,
    ReminderDigest,
    ReminderOccurrence,
    ReminderPreference,
    ReminderRoleCard,
)
from models.user import User  # noqa: E402
from schemas.user import UserCreate  # noqa: E402
from services.auth import get_current_admin  # noqa: E402
from services.reminder_preferences import (  # noqa: E402
    DEFAULT_CADENCE_OFFSETS,
    ensure_preferences,
    normalize_cadence_offsets,
    normalize_language,
    resolve_preferences,
    update_preferences,
    validate_timezone,
)
from services.reminder_seeds import seed_builtin_role_cards  # noqa: E402


class ReminderFoundationTests(unittest.TestCase):
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
            db.add(User(username="student", email="student@example.com", password_hash="x"))
            db.commit()

    def test_all_reminder_models_are_in_authoritative_metadata(self):
        expected = {
            ReminderRoleCard.__tablename__,
            ReminderPreference.__tablename__,
            ReminderOccurrence.__tablename__,
            ReminderDigest.__tablename__,
            ReminderDelivery.__tablename__,
            LLMUsageRecord.__tablename__,
        }
        self.assertTrue(expected.issubset(Base.metadata.tables))
        self.assertIn("is_admin", User.__table__.columns)

    def test_builtin_cards_seed_exactly_once(self):
        with self.SessionLocal() as db:
            first = seed_builtin_role_cards(db)
            second = seed_builtin_role_cards(db)
            self.assertEqual(3, len(first))
            self.assertEqual(3, len(second))
            cards = db.query(ReminderRoleCard).order_by(ReminderRoleCard.id).all()
            self.assertEqual(
                ["friendly-warm-guy", "tech-geek", "sweet-high-school-girl"],
                [card.slug for card in cards],
            )
            self.assertTrue(all(card.is_builtin for card in cards))
            self.assertIn("非性化", cards[2].personality)
            cards[1].is_active = False
            db.commit()
            seed_builtin_role_cards(db)
            db.refresh(cards[1])
            self.assertFalse(cards[1].is_active)

    def test_read_through_defaults_and_persist_once(self):
        with self.SessionLocal() as db:
            seed_builtin_role_cards(db)
            resolved = resolve_preferences(db, 1)
            self.assertEqual("Asia/Shanghai", resolved.timezone)
            self.assertEqual("zh-CN", resolved.language)
            self.assertEqual(DEFAULT_CADENCE_OFFSETS, resolved.cadence_offsets)
            self.assertEqual("friendly-warm-guy", resolved.role_card.slug)
            self.assertIsNone(resolved.persisted_id)

            first = ensure_preferences(db, 1)
            second = ensure_preferences(db, 1)
            db.commit()
            self.assertEqual(first.id, second.id)
            self.assertEqual(1, db.query(ReminderPreference).count())

    def test_preference_validation_and_inactive_card_fallback(self):
        with self.SessionLocal() as db:
            cards = seed_builtin_role_cards(db)
            row = update_preferences(
                db,
                1,
                language="en-us",
                timezone="America/New_York",
                cadence_offsets=[-7, 2, 1, 0, -1, -3],
                role_card_id=cards[1].id,
                role_card_supplied=True,
            )
            self.assertEqual("en-US", row.language)
            cards[1].is_active = False
            db.commit()
            self.assertEqual("friendly-warm-guy", resolve_preferences(db, 1).role_card.slug)

            for invalid in ("", "Moon/Base", "../UTC"):
                with self.assertRaises(ValueError):
                    validate_timezone(invalid)
            for invalid in ("", "中文", "x"):
                with self.assertRaises(ValueError):
                    normalize_language(invalid)
            with self.assertRaises(ValueError):
                normalize_cadence_offsets([2, 1])

    def test_admin_status_is_server_controlled(self):
        with self.SessionLocal() as db:
            user = db.query(User).filter(User.id == 1).one()
            self.assertFalse(user.is_admin)
            with self.assertRaises(HTTPException) as raised:
                get_current_admin(user)
            self.assertEqual(403, raised.exception.status_code)
            user.is_admin = True
            self.assertEqual(user, get_current_admin(user))

        request = UserCreate(
            username="new-user",
            email="new@example.com",
            password="secret1",
            verification_token="x" * 32,
            is_admin=True,
        )
        self.assertNotIn("is_admin", request.model_dump())

    def test_role_card_edits_do_not_rewrite_historical_digest_snapshot(self):
        with self.SessionLocal() as db:
            card = seed_builtin_role_cards(db)[0]
            digest = ReminderDigest(
                user_id=1,
                local_date=date(2026, 8, 3),
                timezone="Asia/Shanghai",
                language="zh-CN",
                role_card_id=card.id,
                item_snapshot=[{"item_type": "task", "item_id": 9, "title": "Stored"}],
                subject="Stored subject",
                body_text="Stored body",
            )
            db.add(digest)
            db.commit()
            card.speaking_style = "Changed later"
            db.commit()
            db.refresh(digest)
            self.assertEqual("Stored subject", digest.subject)
            self.assertEqual("Stored body", digest.body_text)
            self.assertEqual("Stored", digest.item_snapshot[0]["title"])


if __name__ == "__main__":
    unittest.main()
