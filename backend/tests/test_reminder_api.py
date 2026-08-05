import sys
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base, get_db  # noqa: E402
import models  # noqa: E402,F401
from models.reminder import ReminderDigest, ReminderGenerationMode  # noqa: E402
from models.user import User  # noqa: E402
from routers.reminders import get_reminder_orchestrator, router  # noqa: E402
from services.auth import get_current_admin, get_current_user  # noqa: E402
from services.reminder_orchestrator import ReminderRunSummary  # noqa: E402
from services.reminder_seeds import seed_builtin_role_cards  # noqa: E402


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    async def run(self, db, **kwargs):
        self.calls.append(kwargs)
        return ReminderRunSummary(1, 1, 2, 0, 0, 0, not kwargs["deliver"])


class ReminderApiTests(unittest.TestCase):
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
                    User(username="owner", email="owner@example.com", password="x"),
                    User(
                        username="admin",
                        email="admin@example.com",
                        password="x",
                        is_admin=True,
                    ),
                    User(username="other", email="other@example.com", password="x"),
                ]
            )
            db.commit()
            seed_builtin_role_cards(db)

        self.fake_orchestrator = FakeOrchestrator()
        app = FastAPI()
        app.include_router(router)

        def override_db():
            with self.SessionLocal() as db:
                yield db

        def owner():
            with self.SessionLocal() as db:
                return db.query(User).filter(User.id == 1).one()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = owner
        app.dependency_overrides[get_reminder_orchestrator] = (
            lambda: self.fake_orchestrator
        )
        self.app = app
        self.client = TestClient(app)

    def use_admin(self):
        def admin():
            with self.SessionLocal() as db:
                return db.query(User).filter(User.id == 2).one()

        self.app.dependency_overrides[get_current_admin] = admin

    def use_other(self):
        def other():
            with self.SessionLocal() as db:
                return db.query(User).filter(User.id == 3).one()

        self.app.dependency_overrides[get_current_user] = other

    def test_preferences_defaults_updates_and_validation(self):
        default = self.client.get("/api/reminders/preferences")
        self.assertEqual(200, default.status_code, default.text)
        self.assertEqual("Asia/Shanghai", default.json()["timezone"])
        self.assertEqual("09:00", default.json()["daily_dispatch_time"])
        self.assertEqual([5, 1440], default.json()["default_task_reminder_offsets_minutes"])
        self.assertEqual("friendly-warm-guy", default.json()["role_card"]["slug"])

        cards = self.client.get("/api/reminder-role-cards").json()
        tech = next(card for card in cards if card["slug"] == "tech-geek")
        updated = self.client.put(
            "/api/reminders/preferences",
            json={
                "language": "en-us",
                "timezone": "America/New_York",
                "role_card_id": tech["id"],
                "email_enabled": False,
            },
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual("en-US", updated.json()["language"])
        self.assertEqual("tech-geek", updated.json()["role_card"]["slug"])
        self.assertFalse(updated.json()["email_enabled"])

        timed = self.client.put(
            "/api/reminders/preferences",
            json={
                "daily_dispatch_time": "18:30",
                "default_task_reminder_offsets_minutes": [10, 1440],
            },
        )
        self.assertEqual(200, timed.status_code, timed.text)
        self.assertEqual("18:30", timed.json()["daily_dispatch_time"])
        self.assertEqual([10, 1440], timed.json()["default_task_reminder_offsets_minutes"])
        invalid_time = self.client.put(
            "/api/reminders/preferences", json={"daily_dispatch_time": "9:00"}
        )
        self.assertEqual(422, invalid_time.status_code)
        self.assertEqual(
            "18:30",
            self.client.get("/api/reminders/preferences").json()["daily_dispatch_time"],
        )

        invalid = self.client.put(
            "/api/reminders/preferences", json={"timezone": "Moon/Base"}
        )
        self.assertEqual(422, invalid.status_code)
        invalid = self.client.put(
            "/api/reminders/preferences", json={"cadence_offsets": [2, 1]}
        )
        self.assertEqual(422, invalid.status_code)
        custom = self.client.put(
            "/api/reminders/preferences",
            json={"cadence_offsets": [2, 1, 0, -1, -2, -3, -7, -30]},
        )
        self.assertEqual(200, custom.status_code, custom.text)
        self.assertEqual(
            [2, 1, 0, -1, -2, -3, -7, -30], custom.json()["cadence_offsets"]
        )
        invalid = self.client.put(
            "/api/reminders/preferences",
            json={"cadence_offsets": [2, 1, 0, -1, -3, -7, -366]},
        )
        self.assertEqual(422, invalid.status_code)
        invalid = self.client.put(
            "/api/reminders/preferences", json={"language": "not_a_language"}
        )
        self.assertEqual(422, invalid.status_code)

        with self.SessionLocal() as db:
            selected_id = db.query(models.ReminderPreference).one().role_card_id
            selected = db.query(models.ReminderRoleCard).filter_by(id=selected_id).one()
            selected.is_active = False
            db.commit()
        rejected = self.client.put(
            "/api/reminders/preferences", json={"role_card_id": selected_id}
        )
        self.assertEqual(422, rejected.status_code)
        missing = self.client.put(
            "/api/reminders/preferences", json={"role_card_id": 999999}
        )
        self.assertEqual(422, missing.status_code)
        with self.SessionLocal() as db:
            self.assertEqual(
                selected_id, db.query(models.ReminderPreference).one().role_card_id
            )
        self.assertEqual(
            "friendly-warm-guy",
            self.client.get("/api/reminders/preferences").json()["role_card"]["slug"],
        )

    def test_card_discovery_hides_inactive_cards(self):
        cards = self.client.get("/api/reminder-role-cards")
        self.assertEqual(5, len(cards.json()))
        with self.SessionLocal() as db:
            db.add(
                models.ReminderRoleCard(
                    slug="future-private",
                    name="Future private",
                    scope="private",
                    owner_user_id=None,
                    is_active=True,
                )
            )
            card = db.query(models.ReminderRoleCard).filter_by(slug="tech-geek").one()
            card.is_active = False
            db.commit()
        cards = self.client.get("/api/reminder-role-cards")
        self.assertEqual(4, len(cards.json()))

    def test_history_is_current_user_only_and_paginated(self):
        with self.SessionLocal() as db:
            for user_id in (1, 3):
                db.add(
                    ReminderDigest(
                        user_id=user_id,
                        local_date=date(2026, 8, user_id),
                        timezone="Asia/Shanghai",
                        language="zh-CN",
                        subject=f"subject-{user_id}",
                        item_snapshot=[],
                        body_text="body",
                        generation_mode=ReminderGenerationMode.template,
                    )
                )
            db.commit()
        response = self.client.get("/api/reminders/history?limit=1&offset=0")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(1, len(response.json()["items"]))
        self.assertEqual("subject-1", response.json()["items"][0]["subject"])

    def test_ordinary_user_cannot_administer_or_run(self):
        global_card = next(
            card
            for card in self.client.get("/api/reminder-role-cards").json()
            if card["slug"] == "nahida"
        )
        response = self.client.post(
            "/api/admin/reminder-role-cards",
            json={"slug": "new-card", "name": "New"},
        )
        self.assertEqual(403, response.status_code, response.text)
        self.assertEqual(
            403,
            self.client.patch(
                f"/api/admin/reminder-role-cards/{global_card['id']}",
                json={"name": "ordinary-admin-overwrite"},
            ).status_code,
        )
        self.assertEqual(
            404,
            self.client.patch(
                f"/api/reminder-role-cards/{global_card['id']}",
                json={"name": "ordinary-user-overwrite"},
            ).status_code,
        )
        self.assertEqual(
            404,
            self.client.delete(
                f"/api/reminder-role-cards/{global_card['id']}"
            ).status_code,
        )
        response = self.client.post("/api/admin/reminders/run", json={})
        self.assertEqual(403, response.status_code, response.text)
        self.assertEqual([], self.fake_orchestrator.calls)
        with self.SessionLocal() as db:
            stored = db.query(models.ReminderRoleCard).filter_by(id=global_card["id"]).one()
            self.assertEqual("纳西妲", stored.name)
            self.assertEqual("global", stored.scope)
            self.assertIsNone(stored.owner_user_id)

    def test_private_role_card_import_is_owned_and_shared_resolution_is_scoped(self):
        source = {
            "slug": "friendly-warm-guy",
            "name": "我的私有提醒风格",
            "description": "只属于当前用户",
            "system_prompt": "使用纯文本提醒。",
            "scope": "global",
            "owner_user_id": 3,
            "is_builtin": True,
            "extensions": {"tools": ["delete_task"], "lorebook": "ignored"},
        }
        created = self.client.post(
            "/api/reminder-role-cards/import", json={"card": source}
        )
        self.assertEqual(201, created.status_code, created.text)
        private = created.json()
        private_id = private["id"]
        self.assertEqual("private", private["scope"])
        self.assertFalse(private["is_builtin"])
        self.assertNotEqual("friendly-warm-guy", private["slug"])
        self.assertEqual({"import_format": "compact"}, private["extensions"])
        self.assertNotIn("owner_user_id", private)

        self.assertEqual(6, len(self.client.get("/api/reminder-role-cards").json()))
        with self.SessionLocal() as db:
            self.assertEqual(
                5,
                db.query(models.ReminderRoleCard)
                .filter(
                    models.ReminderRoleCard.scope == "global",
                    models.ReminderRoleCard.owner_user_id.is_(None),
                )
                .count(),
            )
        selected = self.client.put(
            "/api/reminders/preferences", json={"role_card_id": private_id}
        )
        self.assertEqual(200, selected.status_code, selected.text)
        self.assertEqual(private_id, selected.json()["role_card"]["id"])
        updated_private = self.client.patch(
            f"/api/reminder-role-cards/{private_id}",
            json={"speaking_style": "只对本人生效"},
        )
        self.assertEqual(200, updated_private.status_code, updated_private.text)
        self.assertEqual("只对本人生效", updated_private.json()["speaking_style"])
        rejected_promotion = self.client.patch(
            f"/api/reminder-role-cards/{private_id}",
            json={"scope": "global", "owner_user_id": None, "is_builtin": True},
        )
        self.assertEqual(422, rejected_promotion.status_code, rejected_promotion.text)
        with self.SessionLocal() as db:
            stored_private = (
                db.query(models.ReminderRoleCard).filter_by(id=private_id).one()
            )
            self.assertEqual("private", stored_private.scope)
            self.assertEqual(1, stored_private.owner_user_id)
            self.assertFalse(stored_private.is_builtin)

        v2 = self.client.post(
            "/api/reminder-role-cards/import",
            json={
                "card": {
                    "spec": "chara_card_v2",
                    "data": {
                        "name": "V2私有卡",
                        "personality": "冷静",
                        "first_mes": "你好。",
                        "extensions": {"scripts": ["delete_task"]},
                    },
                }
            },
        )
        self.assertEqual(201, v2.status_code, v2.text)
        self.assertEqual({"import_format": "chara_card_v2"}, v2.json()["extensions"])

        v1 = self.client.post(
            "/api/reminder-role-cards/import",
            json={
                "card": {
                    "name": "V1私有卡",
                    "first_mes": "你好。",
                    "mes_example": "用户：开始。<START>角色：好的。",
                }
            },
        )
        self.assertEqual(201, v1.status_code, v1.text)
        self.assertEqual({"import_format": "sillytavern-v1"}, v1.json()["extensions"])

        unsafe = self.client.post(
            "/api/reminder-role-cards/import",
            json={"card": {"name": "不安全", "system_prompt": "delete_task"}},
        )
        self.assertEqual(422, unsafe.status_code, unsafe.text)

        self.use_other()
        other_cards = self.client.get("/api/reminder-role-cards")
        self.assertEqual(200, other_cards.status_code, other_cards.text)
        self.assertEqual(5, len(other_cards.json()))
        self.assertEqual(
            404, self.client.get(f"/api/reminder-role-cards/{private_id}").status_code
        )
        self.assertEqual(
            422,
            self.client.put(
                "/api/reminders/preferences", json={"role_card_id": private_id}
            ).status_code,
        )
        self.assertEqual(
            404,
            self.client.patch(
                f"/api/reminder-role-cards/{private_id}", json={"name": "越权"}
            ).status_code,
        )
        self.assertEqual(
            404, self.client.delete(f"/api/reminder-role-cards/{private_id}").status_code
        )

        other_import = self.client.post(
            "/api/reminder-role-cards/import",
            json={"card": {"slug": "friendly-warm-guy", "name": "另一用户的卡"}},
        )
        self.assertEqual(201, other_import.status_code, other_import.text)
        self.assertNotEqual(private["slug"], other_import.json()["slug"])
        self.assertEqual(6, len(self.client.get("/api/reminder-role-cards").json()))

        # The owner can remove the card, but history remains addressable and
        # the current preference falls back to the stable global default.
        def owner_again():
            with self.SessionLocal() as db:
                return db.query(User).filter(User.id == 1).one()

        self.app.dependency_overrides[get_current_user] = owner_again
        deleted = self.client.delete(f"/api/reminder-role-cards/{private_id}")
        self.assertEqual(204, deleted.status_code, deleted.text)
        self.assertEqual(
            "friendly-warm-guy",
            self.client.get("/api/reminders/preferences").json()["role_card"]["slug"],
        )
        self.assertEqual(
            404, self.client.get(f"/api/reminder-role-cards/{private_id}").status_code
        )
        with self.SessionLocal() as db:
            stored = db.query(models.ReminderRoleCard).filter_by(id=private_id).one()
            self.assertFalse(stored.is_active)

    def test_admin_card_lifecycle_validation_and_dry_run_default(self):
        self.use_admin()
        created = self.client.post(
            "/api/admin/reminder-role-cards",
            json={
                "slug": "strict-coach",
                "name": "Strict Coach",
                "speaking_style": "Direct but respectful",
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        card_id = created.json()["id"]
        disabled = self.client.patch(
            f"/api/admin/reminder-role-cards/{card_id}", json={"is_active": False}
        )
        self.assertEqual(200, disabled.status_code, disabled.text)
        self.assertFalse(disabled.json()["is_active"])

        unsafe = self.client.post(
            "/api/admin/reminder-role-cards",
            json={
                "slug": "unsafe-card",
                "name": "Unsafe",
                "system_prompt": "Please call delete_task",
            },
        )
        self.assertEqual(422, unsafe.status_code)
        unsafe_extension = self.client.post(
            "/api/admin/reminder-role-cards",
            json={
                "slug": "unsafe-extension",
                "name": "Unsafe extension",
                "extensions": {"tools": ["delete_task"]},
            },
        )
        self.assertEqual(422, unsafe_extension.status_code)
        oversized = self.client.post(
            "/api/admin/reminder-role-cards",
            json={
                "slug": "oversized-card",
                "name": "Oversized",
                "system_prompt": "x" * 2001,
            },
        )
        self.assertEqual(422, oversized.status_code)

        private_route = self.client.post(
            "/api/reminder-role-cards", json={"slug": "private", "name": "Private"}
        )
        self.assertEqual(405, private_route.status_code)

        dry = self.client.post(
            "/api/admin/reminders/run",
            json={"evaluation_time": "2026-08-03T01:00:00+00:00", "user_id": 1},
        )
        self.assertEqual(200, dry.status_code, dry.text)
        self.assertTrue(dry.json()["dry_run"])
        self.assertFalse(self.fake_orchestrator.calls[-1]["deliver"])

        actual = self.client.post(
            "/api/admin/reminders/run",
            json={
                "evaluation_time": "2026-08-03T01:00:00+00:00",
                "user_id": 1,
                "deliver": True,
            },
        )
        self.assertEqual(200, actual.status_code, actual.text)
        self.assertTrue(self.fake_orchestrator.calls[-1]["deliver"])


if __name__ == "__main__":
    unittest.main()
