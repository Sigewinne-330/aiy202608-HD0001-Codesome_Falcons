import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet
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
from models.app_user import AppUser  # noqa: E402
from models.managebac import ManageBacConnection, ManageBacSyncRun, ManageBacTaskLink  # noqa: E402
from models.task_new import Task  # noqa: E402
from routers.managebac import router  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.managebac_security import FetchedCalendar, ManageBacURLValidationError  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "managebac_calendar.ics"


class ManageBacApiTests(unittest.TestCase):
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
                    AppUser(username="owner", email="owner@example.com", password="x"),
                    AppUser(username="other", email="other@example.com", password="x"),
                ]
            )
            db.commit()

        app = FastAPI()
        app.include_router(router)

        def override_db():
            with self.SessionLocal() as db:
                yield db

        def owner():
            with self.SessionLocal() as db:
                return db.query(AppUser).filter(AppUser.id == 1).one()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = owner
        self.app = app
        self.client = TestClient(app)
        self.original_key = settings.INTEGRATION_CREDENTIAL_KEY
        settings.INTEGRATION_CREDENTIAL_KEY = Fernet.generate_key().decode("ascii")

    def tearDown(self):
        settings.INTEGRATION_CREDENTIAL_KEY = self.original_key
        self.client.close()

    def use_other_user(self):
        def other():
            with self.SessionLocal() as db:
                return db.query(AppUser).filter(AppUser.id == 2).one()

        self.app.dependency_overrides[get_current_user] = other

    def add_connection(self, *, user_id=1, status="active", enabled=True):
        with self.SessionLocal() as db:
            row = ManageBacConnection(
                user_id=user_id,
                encrypted_feed_url="encrypted-private-value",
                feed_host=f"school-{user_id}.managebac.com",
                status=status,
                enabled=enabled,
                sync_interval_minutes=10,
                next_sync_at=datetime(2026, 8, 18, 12, 0),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id

    def test_disconnected_and_connected_status_never_expose_encrypted_url(self):
        disconnected = self.client.get("/api/integrations/managebac/status")
        self.assertEqual(200, disconnected.status_code, disconnected.text)
        self.assertEqual(False, disconnected.json()["connected"])

        self.add_connection()
        connected = self.client.get("/api/integrations/managebac/status")
        self.assertEqual(200, connected.status_code, connected.text)
        body = connected.json()
        self.assertEqual(True, body["connected"])
        self.assertEqual("school-1.managebac.com", body["feed_host"])
        self.assertNotIn("encrypted", connected.text)
        self.assertNotIn("feed_url", connected.text)

    def test_connect_imports_fixture_and_response_does_not_echo_secret(self):
        secret_url = "webcal://hanacademy.managebac.com/student/events/private-token.ics"
        fetched = FetchedCalendar(
            http_status=200,
            content=FIXTURE.read_bytes(),
            etag='"fixture-v1"',
            last_modified="Tue, 18 Aug 2026 04:00:00 GMT",
        )
        with patch(
            "services.managebac_sync.fetch_calendar",
            new=AsyncMock(return_value=fetched),
        ), patch("services.schedule_triggers.analyze_after_mutation"):
            response = self.client.post(
                "/api/integrations/managebac/connect",
                json={"feed_url": secret_url},
            )
            reconnected = self.client.post(
                "/api/integrations/managebac/connect",
                json={
                    "feed_url": "webcal://hanacademy.managebac.com/student/events/replacement-token.ics"
                },
            )

        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(2, body["sync"]["added_count"])
        self.assertEqual(2, body["validation"]["importable_items"])
        self.assertNotIn("private-token", response.text)
        self.assertEqual(200, reconnected.status_code, reconnected.text)
        self.assertEqual(0, reconnected.json()["sync"]["added_count"])
        self.assertEqual(2, reconnected.json()["sync"]["unchanged_count"])
        self.assertNotIn("replacement-token", reconnected.text)
        with self.SessionLocal() as db:
            connection = db.query(ManageBacConnection).one()
            self.assertNotEqual(secret_url, connection.encrypted_feed_url)
            self.assertEqual(1, db.query(ManageBacConnection).count())
            self.assertEqual(2, db.query(Task).count())
            self.assertEqual(2, db.query(ManageBacTaskLink).count())

    def test_pause_resume_reconnect_guard_and_user_scoped_runs(self):
        owner_connection = self.add_connection()
        other_connection = self.add_connection(user_id=2)
        with self.SessionLocal() as db:
            db.add_all(
                [
                    ManageBacSyncRun(
                        connection_id=owner_connection,
                        trigger="manual",
                        status="success",
                        started_at=datetime(2026, 8, 18, 10, 0),
                        finished_at=datetime(2026, 8, 18, 10, 1),
                    ),
                    ManageBacSyncRun(
                        connection_id=other_connection,
                        trigger="automatic",
                        status="failed",
                        started_at=datetime(2026, 8, 18, 11, 0),
                        finished_at=datetime(2026, 8, 18, 11, 1),
                    ),
                ]
            )
            db.commit()

        paused = self.client.patch(
            "/api/integrations/managebac/settings",
            json={"enabled": False},
        )
        self.assertEqual(200, paused.status_code, paused.text)
        self.assertEqual("paused", paused.json()["status"])
        self.assertIsNone(paused.json()["next_sync_at"])

        resumed = self.client.patch(
            "/api/integrations/managebac/settings",
            json={"enabled": True},
        )
        self.assertEqual(200, resumed.status_code, resumed.text)
        self.assertEqual("active", resumed.json()["status"])

        runs = self.client.get("/api/integrations/managebac/runs")
        self.assertEqual(200, runs.status_code, runs.text)
        self.assertEqual(["manual"], [row["trigger"] for row in runs.json()["items"]])

        with self.SessionLocal() as db:
            row = db.query(ManageBacConnection).filter_by(id=owner_connection).one()
            row.status = "reconnect_required"
            row.enabled = False
            db.commit()
        rejected = self.client.patch(
            "/api/integrations/managebac/settings",
            json={"enabled": True},
        )
        self.assertEqual(409, rejected.status_code, rejected.text)

    def test_validation_error_is_structured_and_does_not_echo_token(self):
        secret_url = "https://evil.example/private-token.ics"
        error = ManageBacURLValidationError("host_not_allowed", "不是允许的 ManageBac 域名")
        with patch(
            "routers.managebac.validate_managebac_feed",
            new=AsyncMock(side_effect=error),
        ):
            response = self.client.post(
                "/api/integrations/managebac/validate",
                json={"feed_url": secret_url},
            )
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual("host_not_allowed", response.json()["detail"]["code"])
        self.assertNotIn("private-token", response.text)

    def test_manual_sync_respects_worker_lease(self):
        connection_id = self.add_connection()
        with self.SessionLocal() as db:
            row = db.query(ManageBacConnection).filter_by(id=connection_id).one()
            row.lease_owner = "automatic-worker"
            row.lease_expires_at = datetime.utcnow() + timedelta(minutes=2)
            db.commit()
        response = self.client.post("/api/integrations/managebac/sync")
        self.assertEqual(429, response.status_code, response.text)
        self.assertEqual("sync_in_progress", response.json()["detail"]["code"])

    def test_disconnect_explicitly_removes_children_and_optionally_tasks(self):
        fetched = FetchedCalendar(
            http_status=200,
            content=FIXTURE.read_bytes(),
            etag=None,
            last_modified=None,
        )
        with patch(
            "services.managebac_sync.fetch_calendar",
            new=AsyncMock(return_value=fetched),
        ), patch("services.schedule_triggers.analyze_after_mutation"):
            connected = self.client.post(
                "/api/integrations/managebac/connect",
                json={
                    "feed_url": "webcal://hanacademy.managebac.com/student/events/private-token.ics"
                },
            )
        self.assertEqual(200, connected.status_code, connected.text)

        with patch("services.schedule_triggers.analyze_after_mutation"):
            response = self.client.delete(
                "/api/integrations/managebac/disconnect?delete_imported_tasks=true"
            )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(2, response.json()["deleted_tasks"])
        with self.SessionLocal() as db:
            self.assertEqual(0, db.query(ManageBacConnection).count())
            self.assertEqual(0, db.query(ManageBacTaskLink).count())
            self.assertEqual(0, db.query(ManageBacSyncRun).count())
            self.assertEqual(0, db.query(Task).count())


if __name__ == "__main__":
    unittest.main()
