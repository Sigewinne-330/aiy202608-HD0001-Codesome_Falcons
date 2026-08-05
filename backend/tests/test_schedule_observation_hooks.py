import sys
import unittest
from datetime import date, timedelta
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
from models.schedule_personalization import SchedulingDecisionEvent  # noqa: E402
from models.scheduling import ScheduleIntervention, SchedulePlan, SchedulePlanItem  # noqa: E402
from models.task_new import Task, TaskType  # noqa: E402
from schemas.scheduling import (  # noqa: E402
    InterventionResolveRequest,
    PlanApplyRequest,
    PlanCreateRequest,
    PreflightRequest,
    ScheduleDecision,
    SchedulingPreferenceUpdate,
)
from services.schedule_lifecycle import (  # noqa: E402
    apply_plan,
    create_plan,
    preflight_creation,
    resolve_intervention,
    update_preferences,
)
from services.schedule_observation_hooks import capture_plan_preview_after_commit  # noqa: E402
from services.schedule_personalization_config import PersonalizationRuntimeConfig  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class ScheduleObservationHookTests(unittest.TestCase):
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
            db.add(AppUser(username="hook-user", password="x", balance=10000))
            db.commit()

    @staticmethod
    def _capture_config():
        return PersonalizationRuntimeConfig(
            master_enabled=True,
            observation_capture_enabled=True,
        )

    @staticmethod
    def _enable_consent(db):
        consent = get_or_create_private_consent(db, 1)
        consent.operational_personalization_enabled = True
        db.commit()

    @staticmethod
    def _add_overload(db):
        target = date.today() + timedelta(days=1)
        for index in range(3):
            db.add(Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name=f"private-{index}",
                title=f"private title {index}",
                description=f"private description {index}",
                deadline=target,
                estimated_hours=2,
                status="todo",
            ))
        db.commit()
        return target

    def test_preview_hook_captures_only_structured_safe_context(self):
        with self.SessionLocal() as db:
            self._enable_consent(db)
            self._add_overload(db)
            update_preferences(db, 1, SchedulingPreferenceUpdate(
                default_capacity_hours=2,
                reserve_ratio=0,
                max_chunk_hours=2,
            ))
            result = create_plan(db, 1, PlanCreateRequest(profile="balanced"))
            plan = db.query(SchedulePlan).filter_by(id=result["id"]).one()
            items = db.query(SchedulePlanItem).filter_by(plan_id=plan.id).all()
            self.assertGreater(len(items), 0)
            status = capture_plan_preview_after_commit(
                db,
                1,
                plan,
                items,
                config=self._capture_config(),
            )
            self.assertEqual("captured", status.state)
            events = db.query(SchedulingDecisionEvent).all()
            self.assertEqual(len(items), len(events))
            serialized = str([event.context_snapshot for event in events])
            self.assertNotIn("private title", serialized)
            self.assertNotIn("private description", serialized)
            self.assertTrue(all(event.selected_candidate_id is None for event in events))

    def test_preview_and_apply_hook_failures_do_not_rollback_operational_state(self):
        with self.SessionLocal() as db:
            target = self._add_overload(db)
            update_preferences(db, 1, SchedulingPreferenceUpdate(
                default_capacity_hours=2,
                reserve_ratio=0,
                max_chunk_hours=2,
            ))
            with patch(
                "services.schedule_observation_hooks.capture_plan_preview_after_commit",
                side_effect=RuntimeError("analytical store unavailable"),
            ):
                preview = create_plan(db, 1, PlanCreateRequest(profile="balanced"))
            self.assertEqual("preview", db.query(SchedulePlan).filter_by(id=preview["id"]).one().state)
            with patch(
                "services.schedule_observation_hooks.capture_plan_apply_after_commit",
                side_effect=RuntimeError("analytical store unavailable"),
            ):
                applied = apply_plan(
                    db,
                    1,
                    preview["id"],
                    PlanApplyRequest(
                        expected_input_revision=preview["input_revision"],
                        idempotency_key="hook-apply-0001",
                    ),
                )
            self.assertEqual("applied", applied["state"])
            self.assertEqual("applied", db.query(SchedulePlan).filter_by(id=preview["id"]).one().state)
            self.assertTrue(any(
                (row.deadline.date() if hasattr(row.deadline, "date") else row.deadline) != target
                for row in db.query(Task).all()
            ))

    def test_intervention_hook_failure_does_not_rollback_created_source(self):
        with self.SessionLocal() as db:
            target = self._add_overload(db)
            intervention = preflight_creation(db, 1, PreflightRequest(
                source_type="task",
                title="new private source",
                target_date=target,
                estimated_hours=1,
                hard_deadline_date=target + timedelta(days=4),
            ))
            with patch(
                "services.schedule_observation_hooks.capture_intervention_resolution_after_commit",
                side_effect=RuntimeError("analytical store unavailable"),
            ):
                result = resolve_intervention(
                    db,
                    1,
                    intervention["intervention_id"],
                    InterventionResolveRequest(
                        decision=ScheduleDecision.keep_original,
                        idempotency_key="hook-resolve-0001",
                    ),
                )
            self.assertTrue(result["ok"])
            self.assertEqual(4, db.query(Task).count())
            self.assertEqual(
                "resolved",
                db.query(ScheduleIntervention).filter_by(id=intervention["intervention_id"]).one().state,
            )


if __name__ == "__main__":
    unittest.main()
