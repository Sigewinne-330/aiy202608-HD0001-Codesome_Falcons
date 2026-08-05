import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import SchedulingWorkEvent  # noqa: E402
from models.scheduling import ScheduleAuditEvent  # noqa: E402
from models.task_new import Task  # noqa: E402
from services.schedule_lifecycle import record_schedule_outcome  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class ScheduleOutcomeBridgeTests(unittest.TestCase):
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
            db.add(AppUser(username="bridge-user", password="x", balance=10000))
            db.flush()
            db.add(Task(user_id=1, title="bridge source", status="done"))
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            db.commit()

    def test_legacy_completion_writes_exact_typed_provenance_idempotently(self):
        with self.SessionLocal() as db:
            record_schedule_outcome(db, 1, "task", 1, "done", typed_capture_enabled=True)
            record_schedule_outcome(db, 1, "task", 1, "done", typed_capture_enabled=True)
            typed = db.query(SchedulingWorkEvent).one()
            self.assertEqual("completed", typed.event_type)
            self.assertEqual("completed", typed.after_values["terminal_state"])
            self.assertEqual("lifecycle", typed.provenance)
            self.assertEqual("medium", typed.confidence)
            self.assertNotIn("active_minutes", typed.after_values)
            audits = db.query(ScheduleAuditEvent).filter_by(event_type="schedule_outcome_observed").all()
            self.assertEqual(2, len(audits))
            self.assertEqual("completed", audits[0].metadata_json["outcome"])

    def test_typed_failure_cannot_remove_legacy_operational_audit(self):
        with self.SessionLocal() as db, patch(
            "services.schedule_work_events.record_outcome_observation",
            side_effect=RuntimeError("analytical storage unavailable"),
        ):
            record_schedule_outcome(db, 1, "task", 1, "done", typed_capture_enabled=True)
            self.assertEqual(1, db.query(ScheduleAuditEvent).filter_by(event_type="schedule_outcome_observed").count())
            self.assertEqual(0, db.query(SchedulingWorkEvent).count())


if __name__ == "__main__":
    unittest.main()
