import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base, get_db  # noqa: E402
import models  # noqa: F401,E402
from main import app  # noqa: E402
from models.app_user import AppUser  # noqa: E402
from models.task_new import Task, TaskType  # noqa: E402
from models.scheduling import ScheduleAllocation  # noqa: E402
from services.auth import get_current_user  # noqa: E402


class ScheduleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False)
        cls.user = None

        def override_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        def override_user():
            with cls.SessionLocal() as db:
                return db.query(AppUser).filter(AppUser.id == 1).one()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.SessionLocal() as db:
            db.add(AppUser(username="api-scheduler", password="x", balance=10000))
            db.commit()

    def test_flag_and_preferences_and_capacity_routes(self):
        with patch.dict(os.environ, {"SCHEDULING_BALANCER_ENABLED": "false"}):
            self.assertEqual(404, self.client.get("/api/scheduling/preferences").status_code)
        with patch.dict(os.environ, {"SCHEDULING_BALANCER_ENABLED": "true"}):
            response = self.client.put(
                "/api/scheduling/preferences",
                json={"default_capacity_hours": 5, "reserve_ratio": 0.2},
            )
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(5.0, response.json()["default_capacity_hours"])
            target = (date.today() + timedelta(days=2)).isoformat()
            response = self.client.put(
                "/api/scheduling/capacity-overrides",
                json={"local_date": target, "capacity_hours": 0},
            )
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(0.0, response.json()["capacity_hours"])

    def test_preflight_route_is_complete_day_and_side_effect_free(self):
        target = date.today() + timedelta(days=3)
        with self.SessionLocal() as db:
            for index in range(4):
                db.add(Task(
                    user_id=1,
                    task_type=TaskType.todo,
                    id_name=f"item-{index}",
                    title=f"item-{index}",
                    deadline=target,
                    estimated_hours=1,
                    status="todo",
                ))
            db.commit()
        with patch.dict(os.environ, {"SCHEDULING_BALANCER_ENABLED": "true"}):
            response = self.client.post(
                "/api/scheduling/interventions/preflight",
                json={
                    "source_type": "task",
                    "title": "new item",
                    "target_date": target.isoformat(),
                    "estimated_hours": 1,
                },
            )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("overload_intervention", body["kind"])
        self.assertEqual(5, body["projected_count"])
        self.assertEqual(4, len(body["complete_day"]))
        with self.SessionLocal() as db:
            self.assertEqual(4, db.query(Task).count())
        with patch.dict(os.environ, {"SCHEDULING_BALANCER_ENABLED": "true"}):
            history = self.client.get("/api/scheduling/history")
        self.assertEqual(200, history.status_code, history.text)
        self.assertTrue(history.json()["items"])
        self.assertNotIn("new item", history.text)

    def test_calendar_replaces_source_with_active_split_allocations(self):
        source_date = date.today() + timedelta(days=1)
        allocation_date = source_date + timedelta(days=2)
        with self.SessionLocal() as db:
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="split-source",
                title="split-source",
                deadline=source_date,
                estimated_hours=4,
                status="todo",
            )
            db.add(task)
            db.flush()
            db.add(ScheduleAllocation(
                user_id=1,
                source_type="task",
                source_id=task.id,
                local_date=allocation_date,
                effort_hours=2,
                energy_points=2,
                state="active",
            ))
            db.commit()
        response = self.client.get(f"/api/calendar?year={allocation_date.year}&month={allocation_date.month}")
        self.assertEqual(200, response.status_code, response.text)
        days = response.json()["days"]
        source_items = [item for day in days for item in day["tasks"] if item["title"] == "split-source"]
        self.assertEqual(1, len(source_items))
        self.assertEqual("allocation", source_items[0]["type"])

    def test_calendar_suppresses_cross_month_source_and_groups_same_day_chunks(self):
        source_date = date.today() + timedelta(days=2)
        allocation_date = source_date + timedelta(days=90)
        with self.SessionLocal() as db:
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="cross-month-source",
                title="cross-month-source",
                deadline=source_date,
                estimated_hours=4,
                status="todo",
            )
            db.add(task)
            db.flush()
            db.add_all([
                ScheduleAllocation(
                    user_id=1,
                    source_type="task",
                    source_id=task.id,
                    local_date=allocation_date,
                    effort_hours=1,
                    energy_points=1,
                    state="active",
                ),
                ScheduleAllocation(
                    user_id=1,
                    source_type="task",
                    source_id=task.id,
                    local_date=allocation_date,
                    effort_hours=1,
                    energy_points=1,
                    state="active",
                ),
            ])
            db.commit()

        source_response = self.client.get(
            f"/api/calendar?year={source_date.year}&month={source_date.month}"
        )
        self.assertEqual(200, source_response.status_code, source_response.text)
        source_items = [
            item
            for day in source_response.json()["days"]
            for item in day["tasks"]
            if item["title"] == "cross-month-source"
        ]
        self.assertEqual([], source_items)

        allocation_response = self.client.get(
            f"/api/calendar?year={allocation_date.year}&month={allocation_date.month}"
        )
        self.assertEqual(200, allocation_response.status_code, allocation_response.text)
        allocation_items = [
            item
            for day in allocation_response.json()["days"]
            for item in day["tasks"]
            if item["title"] == "cross-month-source"
        ]
        self.assertEqual(1, len(allocation_items))
        self.assertEqual("allocation", allocation_items[0]["type"])

    def test_allocation_replaces_planned_date_but_keeps_personal_deadline(self):
        source_date = date.today() + timedelta(days=2)
        personal_date = source_date + timedelta(days=1)
        allocation_date = source_date + timedelta(days=2)
        with self.SessionLocal() as db:
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="personal-deadline-source",
                title="personal-deadline-source",
                deadline=source_date,
                personal_deadline=personal_date,
                estimated_hours=2,
                status="todo",
            )
            db.add(task)
            db.flush()
            db.add(ScheduleAllocation(
                user_id=1,
                source_type="task",
                source_id=task.id,
                local_date=allocation_date,
                effort_hours=2,
                energy_points=2,
                state="active",
            ))
            db.commit()

        response = self.client.get(
            f"/api/calendar?year={source_date.year}&month={source_date.month}"
        )
        self.assertEqual(200, response.status_code, response.text)
        items = [
            item
            for day in response.json()["days"]
            for item in day["tasks"]
            if item["title"] == "personal-deadline-source"
        ]
        self.assertEqual(2, len(items))
        self.assertEqual({"allocation", "task"}, {item["type"] for item in items})
        task_item = next(item for item in items if item["type"] == "task")
        self.assertEqual("personal", task_item["deadline_kind"])


if __name__ == "__main__":
    unittest.main()
