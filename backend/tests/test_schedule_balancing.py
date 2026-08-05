import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models.app_user import AppUser  # noqa: E402
from models.deadline import Deadline, DeadlineStatus  # noqa: E402
from models.task_new import Priority, Task, TaskType  # noqa: E402
from models.sub_task import SubTask  # noqa: E402
from models.scheduling import (  # noqa: E402
    ScheduleAllocation,
    ScheduleAuditEvent,
    ScheduleCapacityOverride,
    SchedulePlan,
)
from schemas.scheduling import (  # noqa: E402
    CapacityOverrideUpsert,
    InterventionResolveRequest,
    PlanApplyRequest,
    PlanCreateRequest,
    PreflightRequest,
    ScheduleDecision,
    SchedulingPreferenceUpdate,
)
from services.schedule_engine import chunk_effort, dependency_order, rebalance, recommend_date  # noqa: E402
from services.schedule_lifecycle import (  # noqa: E402
    _audit,
    ScheduleError,
    apply_plan,
    create_plan,
    preflight_creation,
    record_schedule_outcome,
    resolve_intervention,
    undo_plan,
    update_preferences,
    upsert_capacity_override,
    history,
)
from services.schedule_projection import load_snapshot  # noqa: E402


class ScheduleBalancingTests(unittest.TestCase):
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
            db.add(AppUser(username="scheduler", password="x", balance=10000))
            db.commit()

    def test_schema_and_projection_are_complete_and_non_duplicating(self):
        # create_all is the startup migration path for new tables and is
        # intentionally safe to run a second time.
        Base.metadata.create_all(self.engine)
        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue({
            "scheduling_preferences",
            "schedule_capacity_overrides",
            "schedule_item_dependencies",
            "schedule_allocations",
            "schedule_interventions",
            "schedule_plans",
            "schedule_plan_items",
            "schedule_audit_events",
        } <= tables)
        target = date.today() + timedelta(days=3)
        with self.SessionLocal() as db:
            parent = Task(
                user_id=1,
                task_type=TaskType.process,
                id_name="timeline",
                title="timeline",
                deadline=target,
                status="todo",
            )
            db.add(parent)
            db.flush()
            db.add(SubTask(task_id=parent.id, name="milestone", notice_time=target, status="pending"))
            db.add(Task(user_id=1, task_type=TaskType.todo, id_name="standalone", title="standalone", deadline=target, status="todo"))
            db.add(Deadline(user_id=1, title="exam", due_date=target, priority=Priority.high, status=DeadlineStatus.pending))
            db.commit()
            snapshot = load_snapshot(db, 1)
            self.assertEqual({"subtask", "task", "deadline"}, {item.source_type for item in snapshot.items})
            self.assertEqual(3, len(snapshot.items_on(target)))
            self.assertEqual(1, len([item for item in snapshot.items if item.source_type == "subtask"]))

    def test_process_parent_is_retained_when_all_subtasks_are_complete(self):
        target = date.today() + timedelta(days=3)
        with self.SessionLocal() as db:
            parent = Task(
                user_id=1,
                task_type=TaskType.process,
                id_name="completed-timeline",
                title="completed-timeline",
                deadline=target,
                estimated_hours=3,
                status="todo",
            )
            db.add(parent)
            db.flush()
            db.add(SubTask(
                task_id=parent.id,
                name="done milestone",
                notice_time=target,
                status="done",
            ))
            db.commit()
            snapshot = load_snapshot(db, 1)
            self.assertEqual(["task"], [item.source_type for item in snapshot.items])
            self.assertEqual(parent.id, snapshot.items[0].source_id)

    def test_fourth_item_intervention_and_all_three_resolution_paths(self):
        target = date.today() + timedelta(days=4)
        with self.SessionLocal() as db:
            for index in range(3):
                db.add(Task(user_id=1, task_type=TaskType.todo, id_name=f"t{index}", title=f"t{index}", deadline=target, estimated_hours=1, status="todo"))
            db.commit()
            ordinary = preflight_creation(db, 1, PreflightRequest(source_type="task", title="third day", target_date=target, estimated_hours=1))
            self.assertEqual("overload_intervention", ordinary["kind"])
            self.assertEqual(4, ordinary["projected_count"])
            self.assertEqual(3, db.query(Task).count())

            keep = resolve_intervention(
                db,
                1,
                ordinary["intervention_id"],
                InterventionResolveRequest(decision=ScheduleDecision.keep_original, idempotency_key="keep-test-123"),
            )
            self.assertTrue(keep["ok"])
            self.assertEqual(4, db.query(Task).count())
            event = db.query(ScheduleAuditEvent).filter_by(event_type="intervention_resolved").one()
            self.assertEqual("keep_original", event.metadata_json["user_choice"])
            self.assertTrue(event.metadata_json["override"])

    def test_accept_recommendation_and_choose_date_are_fresh_checked(self):
        target = date.today() + timedelta(days=4)
        with self.SessionLocal() as db:
            for index in range(3):
                db.add(Task(user_id=1, task_type=TaskType.todo, id_name=f"t{index}", title=f"t{index}", deadline=target, estimated_hours=1, status="todo"))
            db.commit()
            accepted = preflight_creation(db, 1, PreflightRequest(
                source_type="task",
                title="accept me",
                target_date=target,
                estimated_hours=1,
                hard_deadline_date=target + timedelta(days=3),
            ))
            accepted_result = resolve_intervention(
                db,
                1,
                accepted["intervention_id"],
                InterventionResolveRequest(decision=ScheduleDecision.accept_recommendation, idempotency_key="accept-test-123"),
            )
            self.assertTrue(accepted_result["ok"])
            self.assertNotEqual(target, date.fromisoformat(accepted_result["date"]))

            choose = preflight_creation(db, 1, PreflightRequest(
                source_type="task",
                title="choose me",
                target_date=target,
                estimated_hours=1,
                hard_deadline_date=target + timedelta(days=5),
            ))
            chosen_date = target + timedelta(days=2)
            chosen_result = resolve_intervention(
                db,
                1,
                choose["intervention_id"],
                InterventionResolveRequest(decision=ScheduleDecision.choose_date, selected_date=chosen_date, idempotency_key="choose-test-123"),
            )
            self.assertTrue(chosen_result["ok"])
            self.assertEqual(chosen_date.isoformat(), chosen_result["date"])

    def test_vague_work_is_clarified_without_persistence(self):
        target = date.today() + timedelta(days=5)
        with self.SessionLocal() as db:
            for index in range(3):
                db.add(Task(user_id=1, task_type=TaskType.todo, id_name=f"t{index}", title=f"t{index}", deadline=target, estimated_hours=1, status="todo"))
            db.commit()
            result = preflight_creation(db, 1, PreflightRequest(source_type="task", title="写作业", target_date=target))
            self.assertEqual("clarification", result["kind"])
            self.assertEqual(3, db.query(Task).count())

    def test_non_material_vague_work_uses_and_persists_conservative_prior(self):
        target = date.today() + timedelta(days=5)
        with self.SessionLocal() as db:
            for index in range(3):
                db.add(Task(
                    user_id=1,
                    task_type=TaskType.todo,
                    id_name=f"small-{index}",
                    title=f"small-{index}",
                    deadline=target,
                    estimated_hours=0.1,
                    status="todo",
                ))
            db.commit()
            result = preflight_creation(db, 1, PreflightRequest(
                source_type="task",
                title="上传文件",
                target_date=target,
            ))
            self.assertEqual("overload_intervention", result["kind"])
            self.assertIsNone(result["clarification_question"])
            self.assertEqual("uncertainty_not_decision_material", result["clarification_reason_code"])
            self.assertIsNotNone(result["clarification_sensitivity"])
            intervention = db.query(__import__(
                "models.scheduling", fromlist=["ScheduleIntervention"]
            ).ScheduleIntervention).filter_by(id=result["intervention_id"]).one()
            self.assertGreater(intervention.provisional_payload["estimated_hours"], 0)
            self.assertEqual("versioned_product_prior_p90", intervention.provisional_payload["effort_source"])

    def test_capacity_override_and_stable_recommendation(self):
        requested = date.today() + timedelta(days=2)
        with self.SessionLocal() as db:
            update_preferences(db, 1, SchedulingPreferenceUpdate(default_capacity_hours=4, reserve_ratio=0.2))
            upsert_capacity_override(db, 1, CapacityOverrideUpsert(local_date=requested + timedelta(days=1), capacity_hours=0))
            db.add(Task(user_id=1, task_type=TaskType.todo, id_name="existing", title="existing", deadline=requested, estimated_hours=3, status="todo"))
            db.commit()
            snapshot = load_snapshot(db, 1)
            proposed = PreflightRequest(source_type="task", title="new", target_date=requested, estimated_hours=1, hard_deadline_date=requested + timedelta(days=3))
            item = __import__("services.schedule_lifecycle", fromlist=["_item_from_request"])._item_from_request(proposed, 1)
            first = recommend_date(snapshot, item, requested)
            second = recommend_date(snapshot, item, requested)
            self.assertEqual(first.to_dict(), second.to_dict())
            self.assertIsNotNone(first.recommended)
            self.assertNotEqual(first.recommended.date, requested + timedelta(days=1))

    def test_strict_contracts_and_bounded_chunking(self):
        with self.assertRaises(ValidationError):
            SchedulingPreferenceUpdate(min_chunk_hours=3, max_chunk_hours=2)
        with self.assertRaises(ValidationError):
            SchedulingPreferenceUpdate(timezone="Mars/Olympus_Mons")
        with self.assertRaises(ValidationError):
            SchedulingPreferenceUpdate(max_major_items_per_date=4)
        with self.assertRaises(ValidationError):
            PreflightRequest(source_type="subtask", title="milestone", target_date=date.today())
        chunks = chunk_effort(5.5, minimum=0.5, maximum=2.0)
        self.assertEqual(5.5, sum(chunks))
        self.assertTrue(all(value <= 2.0 for value in chunks))
        self.assertLessEqual(sum(value < 0.5 for value in chunks), 1)

    def test_workload_read_failure_is_recoverable_and_creates_nothing(self):
        request = PreflightRequest(
            source_type="task",
            title="safe failure",
            target_date=date.today() + timedelta(days=2),
            estimated_hours=1,
        )
        with self.SessionLocal() as db, patch(
            "services.schedule_lifecycle.load_snapshot",
            side_effect=RuntimeError("temporary read failure"),
        ):
            result = preflight_creation(db, 1, request)
            self.assertEqual("analysis_error", result["state"])
            self.assertEqual("workload_read_failed", result["error_code"])
            self.assertEqual(0, db.query(Task).count())

    def test_revision_covers_score_inputs_and_allocation_override_versions(self):
        target = date.today() + timedelta(days=2)
        with self.SessionLocal() as db:
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="revision",
                title="revision",
                deadline=target,
                estimated_hours=2,
                status="todo",
            )
            db.add(task)
            db.commit()
            first = load_snapshot(db, 1).revision
            task.priority = "urgent"
            task.progress = 50
            db.commit()
            second = load_snapshot(db, 1).revision
            self.assertNotEqual(first, second)

            allocation = ScheduleAllocation(
                user_id=1,
                source_type="task",
                source_id=task.id,
                local_date=target,
                effort_hours=2,
                energy_points=2,
                state="active",
            )
            db.add(allocation)
            db.commit()
            third = load_snapshot(db, 1).revision
            allocation.version = int(allocation.version or 1) + 1
            db.commit()
            fourth = load_snapshot(db, 1).revision
            self.assertNotEqual(third, fourth)

            override = ScheduleCapacityOverride(
                user_id=1,
                local_date=target,
                capacity_hours=4,
                version=1,
            )
            db.add(override)
            db.commit()
            fifth = load_snapshot(db, 1).revision
            override.version += 1
            db.commit()
            sixth = load_snapshot(db, 1).revision
            self.assertNotEqual(fifth, sixth)

    def test_allocation_packets_aggregate_to_one_dependency_work_unit(self):
        target = date.today() + timedelta(days=2)
        with self.SessionLocal() as db:
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="allocated",
                title="allocated",
                deadline=target,
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
                    local_date=target,
                    effort_hours=2,
                    energy_points=2,
                    state="active",
                ),
                ScheduleAllocation(
                    user_id=1,
                    source_type="task",
                    source_id=task.id,
                    local_date=target + timedelta(days=1),
                    effort_hours=2,
                    energy_points=2,
                    state="active",
                ),
            ])
            db.commit()
            snapshot = load_snapshot(db, 1)
            self.assertEqual(2, len(snapshot.items))
            ordered, errors = dependency_order(snapshot)
            self.assertEqual([], errors)
            self.assertEqual(1, len(ordered))
            self.assertAlmostEqual(4.0, ordered[0].estimated_hours)

    def test_balanced_target_ratio_changes_balanced_score(self):
        target = date.today() + timedelta(days=2)
        with self.SessionLocal() as db:
            db.add(Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="peer",
                title="peer",
                deadline=target,
                estimated_hours=2,
                status="todo",
            ))
            db.commit()
            proposed = PreflightRequest(
                source_type="task",
                title="candidate",
                target_date=target,
                estimated_hours=1,
                earliest_start_date=target,
                hard_deadline_date=target,
            )
            item = __import__("services.schedule_lifecycle", fromlist=["_item_from_request"])._item_from_request(proposed, 1)
            update_preferences(db, 1, SchedulingPreferenceUpdate(balanced_target_ratio=0.5))
            low_target = recommend_date(load_snapshot(db, 1), item, target).recommended
            update_preferences(db, 1, SchedulingPreferenceUpdate(balanced_target_ratio=0.95))
            high_target = recommend_date(load_snapshot(db, 1), item, target).recommended
            self.assertIsNotNone(low_target)
            self.assertIsNotNone(high_target)
            self.assertGreater(low_target.score, high_target.score)

    def test_agent_preflight_create_preserves_legacy_task_fields(self):
        from services.scheduling_tools import create_task_with_preflight

        target = date.today() + timedelta(days=3)
        hard = target + timedelta(days=2)
        with self.SessionLocal() as db, patch.dict(
            "os.environ", {"SCHEDULING_BALANCER_ENABLED": "true"}
        ):
            result = create_task_with_preflight(
                db,
                1,
                title="preserved",
                description="body",
                subject="Physics",
                category="ia",
                deadline=target.isoformat(),
                priority="high",
                estimated_hours=2,
                task_type="process",
                status="in_progress",
                personal_deadline=hard.isoformat(),
            )
            self.assertTrue(result["ok"])
            task = db.query(Task).filter(Task.id == result["id"]).one()
            self.assertEqual("Physics", task.subject)
            self.assertEqual("IA", task.category)
            self.assertEqual("in_progress", str(getattr(task.status, "value", task.status)))
            self.assertEqual("process", str(getattr(task.task_type, "value", task.task_type)))
            self.assertEqual(hard, task.hard_deadline_date)

    def test_dependency_cycle_is_infeasible_order(self):
        with self.SessionLocal() as db:
            first = Task(user_id=1, task_type=TaskType.todo, id_name="a", title="a", deadline=date.today() + timedelta(days=2), status="todo")
            second = Task(user_id=1, task_type=TaskType.todo, id_name="b", title="b", deadline=date.today() + timedelta(days=3), status="todo")
            db.add_all([first, second])
            db.commit()
            from models.scheduling import ScheduleItemDependency
            db.add_all([
                ScheduleItemDependency(user_id=1, predecessor_type="task", predecessor_id=first.id, successor_type="task", successor_id=second.id),
                ScheduleItemDependency(user_id=1, predecessor_type="task", predecessor_id=second.id, successor_type="task", successor_id=first.id),
            ])
            db.commit()
            snapshot = load_snapshot(db, 1)
            _, errors = dependency_order(snapshot)
            self.assertTrue(errors)

    def test_rebalance_splits_large_work_within_capacity_and_preserves_effort(self):
        target = date.today() + timedelta(days=1)
        with self.SessionLocal() as db:
            update_preferences(db, 1, SchedulingPreferenceUpdate(
                default_capacity_hours=2,
                reserve_ratio=0,
                min_chunk_hours=0.5,
                max_chunk_hours=2,
            ))
            db.add(Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="large",
                title="large",
                deadline=target,
                estimated_hours=5,
                status="todo",
            ))
            db.commit()
            result = rebalance(load_snapshot(db, 1), "balanced")
            self.assertTrue(result.feasible, result.blockers)
            self.assertEqual(1, len(result.placements))
            chunks = result.placements[0].chunks
            self.assertAlmostEqual(5.0, sum(hours for _, hours in chunks))
            self.assertGreaterEqual(len({chunk_date for chunk_date, _ in chunks}), 3)
            self.assertTrue(all(0 < hours <= 2 for _, hours in chunks))
            self.assertTrue(all(
                row["energy"] <= row["usable_capacity_hours"] + 1e-8
                for row in result.daily_loads
                if row["energy"]
            ))

    def test_rebalance_reports_capacity_deficit_without_partial_plan(self):
        today = date.today()
        hard_deadline = today + timedelta(days=1)
        with self.SessionLocal() as db:
            update_preferences(db, 1, SchedulingPreferenceUpdate(
                default_capacity_hours=1,
                reserve_ratio=0,
                min_chunk_hours=0.5,
                max_chunk_hours=2,
            ))
            db.add(Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="impossible",
                title="impossible",
                deadline=hard_deadline,
                hard_deadline_date=hard_deadline,
                estimated_hours=5,
                status="todo",
            ))
            db.commit()
            result = rebalance(load_snapshot(db, 1), "balanced")
            self.assertFalse(result.feasible)
            self.assertEqual((), result.placements)
            self.assertGreater(result.capacity_deficit_hours, 0)
            self.assertIn("task:1", result.affected_items)
            self.assertIsNotNone(result.earliest_feasible_completion_date)
            self.assertTrue(any(reason.startswith("capacity_deficit:task:1") for reason in result.blockers))

    def test_preview_apply_stale_conflict_and_undo(self):
        target = date.today() + timedelta(days=1)
        with self.SessionLocal() as db:
            db.add(Task(user_id=1, task_type=TaskType.todo, id_name="movable", title="movable", deadline=target, estimated_hours=1, status="todo"))
            db.commit()
            plan = create_plan(db, 1, PlanCreateRequest(profile="balanced", idempotency_key="preview-test-123"))
            self.assertEqual("preview", plan["state"])
            self.assertEqual({"conservative", "balanced", "sprint"}, set(plan["profile_previews"]))
            # A preview with no hard deadline can be applied atomically, even
            # if its item-change list is empty.
            applied = apply_plan(db, 1, plan["id"], PlanApplyRequest(expected_input_revision=plan["input_revision"], idempotency_key="apply-test-123"))
            self.assertEqual("applied", applied["state"])
            undone = undo_plan(db, 1, plan["id"], "undo-test-123")
            self.assertEqual("undone", undone["state"])

    def test_plan_apply_is_owner_scoped_and_stale_safe(self):
        target = date.today() + timedelta(days=1)
        with self.SessionLocal() as db:
            db.add(AppUser(username="other-scheduler", password="x", balance=10000))
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="stale",
                title="stale",
                deadline=target,
                estimated_hours=2,
                status="todo",
            )
            db.add(task)
            db.commit()
            plan = create_plan(db, 1, PlanCreateRequest(profile="balanced"))
            with self.assertRaises(ScheduleError) as foreign:
                apply_plan(
                    db,
                    2,
                    plan["id"],
                    PlanApplyRequest(
                        expected_input_revision=plan["input_revision"],
                        idempotency_key="foreign-apply-123",
                    ),
                )
            self.assertEqual("plan_not_found", foreign.exception.code)

            task.priority = "urgent"
            db.commit()
            with self.assertRaises(ScheduleError) as stale:
                apply_plan(
                    db,
                    1,
                    plan["id"],
                    PlanApplyRequest(
                        expected_input_revision=plan["input_revision"],
                        idempotency_key="stale-apply-123",
                    ),
                )
            self.assertEqual("stale_plan", stale.exception.code)
            db.refresh(task)
            self.assertEqual(target, task.deadline.date() if hasattr(task.deadline, "date") else task.deadline)
            self.assertEqual("preview", db.query(SchedulePlan).filter_by(id=plan["id"]).one().state)

    def test_forced_final_commit_failure_rolls_back_every_planned_item(self):
        target = date.today() + timedelta(days=1)
        with self.SessionLocal() as db:
            update_preferences(db, 1, SchedulingPreferenceUpdate(
                default_capacity_hours=2,
                reserve_ratio=0,
                max_chunk_hours=2,
            ))
            for index in range(3):
                db.add(Task(
                    user_id=1,
                    task_type=TaskType.todo,
                    id_name=f"atomic-{index}",
                    title=f"atomic-{index}",
                    deadline=target,
                    estimated_hours=2,
                    status="todo",
                ))
            db.commit()
            plan = create_plan(db, 1, PlanCreateRequest(profile="balanced"))
            self.assertGreaterEqual(len(plan["item_changes"]), 2)
            before = {
                row.id: (row.deadline, int(row.schedule_version or 1))
                for row in db.query(Task).all()
            }
            with patch.object(db, "commit", side_effect=RuntimeError("forced final commit failure")):
                with self.assertRaises(RuntimeError):
                    apply_plan(
                        db,
                        1,
                        plan["id"],
                        PlanApplyRequest(
                            expected_input_revision=plan["input_revision"],
                            idempotency_key="atomic-apply-123",
                        ),
                    )
            db.rollback()

        with self.SessionLocal() as verify_db:
            after = {
                row.id: (row.deadline, int(row.schedule_version or 1))
                for row in verify_db.query(Task).all()
            }
            self.assertEqual(before, after)
            self.assertEqual(
                "preview",
                verify_db.query(SchedulePlan).filter_by(id=plan["id"]).one().state,
            )
            self.assertEqual(0, verify_db.query(ScheduleAllocation).count())

    def test_split_allocations_are_reversed_and_create_idempotency_survives_apply(self):
        target = date.today() + timedelta(days=1)
        with self.SessionLocal() as db:
            update_preferences(db, 1, SchedulingPreferenceUpdate(
                default_capacity_hours=2,
                reserve_ratio=0,
                min_chunk_hours=0.5,
                max_chunk_hours=2,
            ))
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="split-undo",
                title="split-undo",
                deadline=target,
                estimated_hours=5,
                status="todo",
            )
            db.add(task)
            db.commit()
            plan = create_plan(
                db,
                1,
                PlanCreateRequest(profile="balanced", idempotency_key="create-split-undo"),
            )
            self.assertTrue(plan["item_changes"])
            applied = apply_plan(
                db,
                1,
                plan["id"],
                PlanApplyRequest(
                    expected_input_revision=plan["input_revision"],
                    idempotency_key="apply-split-undo",
                ),
            )
            self.assertEqual("applied", applied["state"])
            self.assertGreater(
                db.query(ScheduleAllocation).filter_by(state="active").count(),
                1,
            )
            replayed_create = create_plan(
                db,
                1,
                PlanCreateRequest(profile="balanced", idempotency_key="create-split-undo"),
            )
            self.assertEqual(plan["id"], replayed_create["id"])

            undone = undo_plan(db, 1, plan["id"], "undo-split-undo")
            self.assertEqual("undone", undone["state"])
            self.assertEqual(0, db.query(ScheduleAllocation).filter_by(state="active").count())
            db.refresh(task)
            self.assertEqual(target, task.deadline.date() if hasattr(task.deadline, "date") else task.deadline)

    def test_schedule_history_sanitizes_metadata_and_affected_items_twice(self):
        with self.SessionLocal() as db:
            _audit(
                db,
                1,
                "privacy_test",
                affected_items=[{
                    "source_type": "task",
                    "source_id": 7,
                    "date": date.today().isoformat(),
                    "title": "private title",
                    "description": "private description",
                    "email": "private@example.com",
                }],
                reason_codes=["balanced_capacity"],
                metadata={
                    "trigger": "test",
                    "provider": "mock",
                    "total_tokens": 12,
                    "api_key": "secret-value",
                    "hidden_prompt": "do not store",
                    "role_card": "private persona",
                    "description": "private body",
                },
            )
            db.commit()
            stored = db.query(ScheduleAuditEvent).filter_by(event_type="privacy_test").one()
            self.assertEqual({"trigger": "test", "provider": "mock", "total_tokens": 12}, stored.metadata_json)
            self.assertEqual(
                [{"source_type": "task", "source_id": 7, "date": date.today().isoformat()}],
                stored.affected_items,
            )
            # Read-time sanitation also protects rows created by an older build.
            stored.metadata_json = {"trigger": "legacy", "api_key": "legacy-secret"}
            stored.affected_items = [{"source_type": "task", "source_id": 7, "title": "legacy-private"}]
            db.commit()
            event = history(db, 1)[0]
            self.assertEqual({"trigger": "legacy"}, event["metadata_json"])
            self.assertEqual([{"source_type": "task", "source_id": 7}], event["affected_items"])

    def test_learning_ready_outcome_is_sanitized_and_never_changes_ranking(self):
        target = date.today() + timedelta(days=2)
        with self.SessionLocal() as db:
            task = Task(
                user_id=1,
                task_type=TaskType.todo,
                id_name="outcome",
                title="outcome",
                deadline=target,
                estimated_hours=1,
                status="todo",
            )
            db.add(task)
            db.commit()
            snapshot = load_snapshot(db, 1)
            proposed = PreflightRequest(
                source_type="task",
                title="candidate",
                target_date=target,
                estimated_hours=1,
            )
            item = __import__("services.schedule_lifecycle", fromlist=["_item_from_request"])._item_from_request(proposed, 1)
            before = recommend_date(snapshot, item, target).to_dict()
            record_schedule_outcome(db, 1, "task", task.id, "done")
            after = recommend_date(load_snapshot(db, 1), item, target).to_dict()
            self.assertEqual(before, after)
            event = db.query(ScheduleAuditEvent).filter_by(event_type="schedule_outcome_observed").one()
            self.assertEqual({
                "source_type": "task",
                "source_id": task.id,
                "completion_state": "done",
                "outcome": "completed",
            }, event.metadata_json)
            self.assertNotIn("title", str(event.metadata_json))

    def test_auto_schedule_is_opt_in_and_uses_the_same_apply_path(self):
        from services.schedule_triggers import analyze_after_mutation

        target = date.today() + timedelta(days=2)
        with self.SessionLocal() as db:
            update_preferences(db, 1, SchedulingPreferenceUpdate(auto_scheduling_enabled=True))
            for index in range(4):
                db.add(Task(user_id=1, task_type=TaskType.todo, id_name=f"auto-{index}", title=f"auto-{index}", deadline=target, estimated_hours=1, status="todo"))
            db.commit()
            with patch.dict("os.environ", {"SCHEDULING_BALANCER_ENABLED": "true"}):
                result = analyze_after_mutation(db, 1, "test_auto")
            self.assertTrue(result["auto_applied"])
            self.assertIsNotNone(result["auto_plan_id"])
            self.assertTrue(db.query(ScheduleAuditEvent).filter_by(event_type="plan_auto_applied").count())
            self.assertTrue(db.query(ScheduleAuditEvent).filter_by(event_type="schedule_internal_notification").count())

    def test_auto_schedule_notification_failure_does_not_rollback_plan(self):
        from services.schedule_triggers import analyze_after_mutation

        target = date.today() + timedelta(days=2)
        with self.SessionLocal() as db:
            update_preferences(db, 1, SchedulingPreferenceUpdate(auto_scheduling_enabled=True))
            for index in range(4):
                db.add(Task(
                    user_id=1,
                    task_type=TaskType.todo,
                    id_name=f"notify-{index}",
                    title=f"notify-{index}",
                    deadline=target,
                    estimated_hours=1,
                    status="todo",
                ))
            db.commit()

            def fail_notification(*_args, **_kwargs):
                raise RuntimeError("notification transport unavailable")

            with patch.dict("os.environ", {"SCHEDULING_BALANCER_ENABLED": "true"}):
                result = analyze_after_mutation(
                    db,
                    1,
                    "test_notification_failure",
                    notification_adapter=fail_notification,
                )
            self.assertTrue(result["auto_applied"])
            self.assertIn("internal_notification_failed", result["post_commit_errors"])
            plan = db.query(SchedulePlan).filter(SchedulePlan.id == result["auto_plan_id"]).one()
            self.assertEqual("applied", plan.state)

    def test_auto_schedule_disabled_or_fixed_work_never_moves(self):
        from services.schedule_triggers import analyze_after_mutation

        target = date.today() + timedelta(days=2)
        with self.SessionLocal() as db:
            for index in range(4):
                db.add(Task(
                    user_id=1,
                    task_type=TaskType.todo,
                    id_name=f"locked-{index}",
                    title=f"locked-{index}",
                    deadline=target,
                    estimated_hours=2,
                    status="todo",
                    is_schedule_locked=True,
                ))
            db.commit()
            before = [row.deadline for row in db.query(Task).order_by(Task.id).all()]
            with patch.dict("os.environ", {"SCHEDULING_BALANCER_ENABLED": "true"}):
                disabled = analyze_after_mutation(db, 1, "auto_disabled")
            self.assertFalse(disabled["auto_applied"])

            update_preferences(db, 1, SchedulingPreferenceUpdate(auto_scheduling_enabled=True))
            with patch.dict("os.environ", {"SCHEDULING_BALANCER_ENABLED": "true"}):
                fixed = analyze_after_mutation(db, 1, "fixed_work")
            self.assertFalse(fixed["auto_applied"])
            self.assertEqual(before, [row.deadline for row in db.query(Task).order_by(Task.id).all()])


if __name__ == "__main__":
    unittest.main()
