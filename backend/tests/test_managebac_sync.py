import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import settings  # noqa: E402
from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models.managebac import ManageBacConnection, ManageBacTaskLink  # noqa: E402
from models.reminder import ReminderPreference, TaskReminderState  # noqa: E402
from models.task_new import Task  # noqa: E402
from models.user import User  # noqa: E402
from services import managebac_sync  # noqa: E402
from services.managebac_sync import connect_managebac_feed, sync_managebac_connection  # noqa: E402
from services.reminder_preferences import resolve_preferences  # noqa: E402
from services.reminder_scheduler import (  # noqa: E402
    claim_due_task_relative_notifications,
    revalidate_task_relative_notification,
)


FIXTURE = Path(__file__).parent / "fixtures" / "managebac_calendar.ics"
FEED_URL = "webcal://school.managebac.com/student/events/token/test-only.ics"
PUBLIC_RESOLVER = lambda _host: ["8.8.8.8"]


def response_transport(state):
    def handler(request: httpx.Request):
        state.setdefault("requests", []).append(request)
        return httpx.Response(200, headers={"ETag": state.get("etag", '"v1"')}, content=state["content"])

    return httpx.MockTransport(handler)


def single_task_feed(*, title="Physics IA First Draft", date_value="20260910", status="CONFIRMED", sequence=1):
    return f"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:task-physics-101@example.managebac.com\r
DTSTART;VALUE=DATE:{date_value}\r
SUMMARY:{title}\r
DESCRIPTION:Task: Submit on ManageBac.\r
CATEGORIES:Physics,Task\r
URL:https://school.managebac.com/student/classes/1/tasks/101\r
STATUS:{status}\r
SEQUENCE:{sequence}\r
END:VEVENT\r
END:VCALENDAR\r
""".encode("utf-8")


class ManageBacSyncTests(unittest.TestCase):
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
        self.original_key = settings.INTEGRATION_CREDENTIAL_KEY
        settings.INTEGRATION_CREDENTIAL_KEY = Fernet.generate_key().decode("ascii")
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.SessionLocal() as db:
            db.add(User(id=1, username="student", email="student@example.com", password="x"))
            db.add(User(id=2, username="student2", email="student2@example.com", password="x"))
            db.add(
                ReminderPreference(
                    user_id=1,
                    timezone="Asia/Shanghai",
                    default_task_reminder_offsets_minutes=[5, 1440],
                )
            )
            db.commit()

    def tearDown(self):
        settings.INTEGRATION_CREDENTIAL_KEY = self.original_key

    def connect(self, db, content=None):
        state = {"content": content or FIXTURE.read_bytes(), "etag": '"v1"'}
        result = asyncio.run(
            connect_managebac_feed(
                db,
                1,
                FEED_URL,
                transport=response_transport(state),
                resolve_addresses=PUBLIC_RESOLVER,
            )
        )
        return result, state

    def test_initial_sync_encrypts_url_creates_tasks_and_is_idempotent_100_times(self):
        with self.SessionLocal() as db:
            (connection, validated, summary), state = self.connect(db)
            self.assertEqual(3, summary["added_count"])
            self.assertEqual(3, db.query(Task).count())
            self.assertEqual(3, db.query(ManageBacTaskLink).count())
            self.assertNotIn("test-only", connection.encrypted_feed_url)

            physics = db.query(Task).filter(Task.subject == "Physics").one()
            self.assertEqual("managebac", physics.effort_source)
            self.assertIsNone(physics.reminder_offsets_minutes)
            self.assertEqual(datetime(2026, 9, 10, 23, 59), physics.deadline)

            for _ in range(100):
                result = asyncio.run(
                    sync_managebac_connection(
                        db,
                        connection,
                        trigger="manual",
                        transport=response_transport(state),
                        resolve_addresses=PUBLIC_RESOLVER,
                    )
                )
                self.assertEqual("success", result["status"])
            self.assertEqual(3, db.query(Task).count())
            self.assertEqual(3, db.query(ManageBacTaskLink).count())

    def test_manual_sync_forces_full_feed_without_conditional_headers(self):
        with self.SessionLocal() as db:
            (_, _, _), state = self.connect(db, single_task_feed())
            connection = db.query(ManageBacConnection).one()
            state["requests"] = []
            result = asyncio.run(
                sync_managebac_connection(
                    db,
                    connection,
                    trigger="manual",
                    transport=response_transport(state),
                    resolve_addresses=PUBLIC_RESOLVER,
                )
            )
            self.assertEqual(200, result["http_status"])
            self.assertEqual(1, len(state["requests"]))
            request = state["requests"][0]
            self.assertNotIn("if-none-match", request.headers)
            self.assertNotIn("if-modified-since", request.headers)

    def test_remote_update_preserves_local_fields_and_invalidates_old_reminder(self):
        with self.SessionLocal() as db:
            (_, _, _), state = self.connect(db, single_task_feed())
            task = db.query(Task).one()
            task.personal_deadline = datetime(2026, 9, 8, 12, 0)
            task.priority = "urgent"
            db.commit()

            preferences = resolve_preferences(db, 1)
            notifications = claim_due_task_relative_notifications(
                db,
                user_id=1,
                preferences=preferences,
                now_utc=datetime(2026, 9, 10, 15, 54, tzinfo=timezone.utc),
            )
            self.assertEqual(1, len(notifications))
            old_notification = notifications[0]

            state["content"] = single_task_feed(
                title="Physics IA Revised Draft",
                date_value="20260912",
                sequence=2,
            )
            state["etag"] = '"v2"'
            connection = db.query(ManageBacConnection).one()
            result = asyncio.run(
                sync_managebac_connection(
                    db,
                    connection,
                    trigger="manual",
                    transport=response_transport(state),
                    resolve_addresses=PUBLIC_RESOLVER,
                )
            )
            self.assertEqual(1, result["updated_count"])
            db.refresh(task)
            self.assertEqual("Physics IA Revised Draft", task.title)
            self.assertEqual(datetime(2026, 9, 12, 23, 59), task.deadline)
            self.assertEqual(datetime(2026, 9, 8, 12, 0), task.personal_deadline)
            self.assertEqual("urgent", task.priority)
            self.assertFalse(revalidate_task_relative_notification(db, old_notification))
            self.assertEqual(TaskReminderState.cancelled, old_notification.state)

    def test_not_modified_response_is_a_successful_noop(self):
        with self.SessionLocal() as db:
            self.connect(db, single_task_feed())
            connection = db.query(ManageBacConnection).one()
            not_modified = httpx.MockTransport(lambda _request: httpx.Response(304))
            result = asyncio.run(
                sync_managebac_connection(
                    db,
                    connection,
                    trigger="automatic",
                    transport=not_modified,
                    resolve_addresses=PUBLIC_RESOLVER,
                )
            )
            self.assertEqual("success", result["status"])
            self.assertEqual(304, result["http_status"])
            self.assertEqual(0, result["added_count"])
            self.assertEqual(0, result["updated_count"])
            self.assertEqual(1, db.query(Task).count())

    def test_explicit_cancel_clears_remote_deadline_but_missing_item_does_not_delete(self):
        with self.SessionLocal() as db:
            (_, _, _), state = self.connect(db, single_task_feed())
            task = db.query(Task).one()
            connection = db.query(ManageBacConnection).one()

            state["content"] = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
            result = asyncio.run(
                sync_managebac_connection(
                    db,
                    connection,
                    trigger="manual",
                    transport=response_transport(state),
                    resolve_addresses=PUBLIC_RESOLVER,
                )
            )
            self.assertEqual("success", result["status"])
            self.assertEqual(1, db.query(Task).count())
            db.refresh(task)
            self.assertIsNotNone(task.deadline)
            self.assertEqual(1, db.query(ManageBacTaskLink).one().missing_count)

            state["content"] = single_task_feed(status="CANCELLED", sequence=3)
            result = asyncio.run(
                sync_managebac_connection(
                    db,
                    connection,
                    trigger="manual",
                    transport=response_transport(state),
                    resolve_addresses=PUBLIC_RESOLVER,
                )
            )
            self.assertEqual(1, result["cancelled_count"])
            db.refresh(task)
            self.assertIsNone(task.deadline)
            self.assertEqual("cancelled", db.query(ManageBacTaskLink).one().remote_state)

    def test_imported_task_appears_in_calendar_and_inherits_default_reminders(self):
        from routers.calendar import get_calendar_data

        with self.SessionLocal() as db:
            self.connect(db, single_task_feed())
            user = db.query(User).filter(User.id == 1).one()
            calendar = get_calendar_data(year=2026, month=9, current_user=user, db=db)
            day = next(row for row in calendar.days if row.date == "2026-09-10")
            self.assertEqual("Physics IA First Draft", day.tasks[0].title)
            self.assertEqual("official", day.tasks[0].deadline_kind)

            notifications = claim_due_task_relative_notifications(
                db,
                user_id=1,
                preferences=resolve_preferences(db, 1),
                now_utc=datetime(2026, 9, 10, 15, 54, tzinfo=timezone.utc),
            )
            self.assertEqual(1, len(notifications))
            self.assertEqual(5, notifications[0].offset_minutes)

    def test_three_permanent_failures_require_reconnect(self):
        with self.SessionLocal() as db:
            self.connect(db, single_task_feed())
            connection = db.query(ManageBacConnection).one()
            failing = httpx.MockTransport(lambda _request: httpx.Response(404))
            for _ in range(3):
                result = asyncio.run(
                    sync_managebac_connection(
                        db,
                        connection,
                        trigger="automatic",
                        transport=failing,
                        resolve_addresses=PUBLIC_RESOLVER,
                    )
                )
                self.assertEqual("failed", result["status"])
            db.refresh(connection)
            self.assertEqual("reconnect_required", connection.status)
            self.assertFalse(connection.enabled)
            self.assertIsNone(connection.next_sync_at)

    def test_repeated_403_remains_retryable_without_disabling_valid_feed(self):
        with self.SessionLocal() as db:
            self.connect(db, single_task_feed())
            connection = db.query(ManageBacConnection).one()
            failing = httpx.MockTransport(lambda _request: httpx.Response(403))
            for _ in range(3):
                result = asyncio.run(
                    sync_managebac_connection(
                        db,
                        connection,
                        trigger="automatic",
                        transport=failing,
                        resolve_addresses=PUBLIC_RESOLVER,
                    )
                )
                self.assertEqual("failed", result["status"])
            db.refresh(connection)
            self.assertEqual("error", connection.status)
            self.assertTrue(connection.enabled)
            self.assertIsNotNone(connection.next_sync_at)

    def test_stale_remote_sequence_cannot_overwrite_or_cancel_a_newer_revision(self):
        with self.SessionLocal() as db:
            (_, _, _), state = self.connect(
                db,
                single_task_feed(title="Newest title", sequence=5),
            )
            connection = db.query(ManageBacConnection).one()
            task = db.query(Task).one()

            state["content"] = single_task_feed(
                title="Stale title",
                date_value="20260901",
                status="CANCELLED",
                sequence=4,
            )
            result = asyncio.run(
                sync_managebac_connection(
                    db,
                    connection,
                    trigger="automatic",
                    transport=response_transport(state),
                    resolve_addresses=PUBLIC_RESOLVER,
                )
            )
            self.assertEqual(1, result["unchanged_count"])
            db.refresh(task)
            self.assertEqual("Newest title", task.title)
            self.assertEqual(datetime(2026, 9, 10, 23, 59), task.deadline)
            link = db.query(ManageBacTaskLink).one()
            self.assertEqual(5, link.remote_sequence)
            self.assertEqual("active", link.remote_state)

    def test_due_worker_isolates_connection_failures_and_releases_leases(self):
        now = managebac_sync.utc_now_naive()
        with self.SessionLocal() as db:
            for user_id in (1, 2):
                db.add(
                    ManageBacConnection(
                        user_id=user_id,
                        encrypted_feed_url="test-only-encrypted",
                        feed_host="school.managebac.com",
                        status="active",
                        enabled=True,
                        sync_interval_minutes=10,
                        next_sync_at=now,
                    )
                )
            db.commit()

        calls = []

        async def isolated_sync(_db, connection, *, trigger):
            calls.append((connection.id, trigger))
            if connection.user_id == 1:
                raise RuntimeError("isolated test failure")
            return {"status": "success"}

        from unittest.mock import patch

        with self.assertLogs(managebac_sync.logger, level="ERROR"):
            with patch.object(managebac_sync, "sync_managebac_connection", new=isolated_sync):
                summary = asyncio.run(
                    managebac_sync.sync_due_managebac_connections(self.SessionLocal)
                )
        self.assertEqual({"evaluated": 2, "succeeded": 1, "failed": 1}, summary)
        self.assertEqual(2, len(calls))
        with self.SessionLocal() as db:
            rows = db.query(ManageBacConnection).all()
            self.assertTrue(all(row.lease_owner is None for row in rows))
            self.assertTrue(all(row.lease_expires_at is None for row in rows))

    def test_unreadable_encrypted_credential_immediately_requires_reconnect(self):
        with self.SessionLocal() as db:
            self.connect(db, single_task_feed())
            connection = db.query(ManageBacConnection).one()
            connection.encrypted_feed_url = "not-a-valid-fernet-value"
            db.commit()
            result = asyncio.run(
                sync_managebac_connection(db, connection, trigger="automatic")
            )
            self.assertEqual("failed", result["status"])
            db.refresh(connection)
            self.assertEqual("reconnect_required", connection.status)
            self.assertFalse(connection.enabled)


if __name__ == "__main__":
    unittest.main()
