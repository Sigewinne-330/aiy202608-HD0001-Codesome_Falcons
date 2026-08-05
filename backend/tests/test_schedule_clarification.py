import sys
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_clarification import (  # noqa: E402
    SensitivityAssumption,
    analyze_clarification_value,
)
from services.schedule_projection import CapacityPolicy, ScheduleSnapshot, WorkItem  # noqa: E402


class ScheduleClarificationTests(unittest.TestCase):
    def setUp(self):
        self.today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        self.policy = CapacityPolicy(
            default_capacity_hours=4,
            reserve_ratio=0.20,
            balanced_target_ratio=0.85,
            min_chunk_hours=0.5,
            max_chunk_hours=2,
            max_major_items_per_date=3,
            same_kind_soft_limit=2,
            switching_soft_limit=3,
            no_deadline_horizon_days=30,
            auto_scheduling_enabled=False,
            timezone="Asia/Shanghai",
        )

    def _item(self, source_id, target, hours, *, deadline=None):
        return WorkItem(
            source_type="task",
            source_id=source_id,
            user_id=1,
            title=f"task {source_id}",
            local_date=target,
            status="todo",
            priority="medium",
            estimated_hours=hours,
            energy_intensity=1,
            effort_source="test",
            is_schedule_locked=False,
            schedule_kind="essay_draft",
            hard_deadline_date=deadline,
        )

    def _snapshot(self, items=()):
        return ScheduleSnapshot(
            user_id=1,
            items=tuple(items),
            dependencies=(),
            preferences=self.policy,
            capacity_overrides={},
            revision="a" * 64,
        )

    def test_asks_one_question_when_safe_date_changes(self):
        target = self.today + timedelta(days=1)
        existing = self._item(1, target, 2.6)
        proposed = replace(
            self._item(99, target, 1, deadline=target + timedelta(days=4)),
            earliest_start_date=target,
        )
        assumptions = (
            SensitivityAssumption("low", 0.5, 0.3),
            SensitivityAssumption("median", 1.5, 0.4),
            SensitivityAssumption("high", 4.0, 0.3),
        )
        result = analyze_clarification_value(self._snapshot((existing,)), proposed, target, assumptions)
        self.assertTrue(result.should_ask)
        self.assertEqual("effort_hours", result.unresolved_field)
        self.assertIsNotNone(result.question)
        self.assertIn("top_date_changes", result.material_changes)
        self.assertEqual(1, len([result.question]))

    def test_does_not_ask_when_uncertainty_cannot_change_decision(self):
        target = self.today + timedelta(days=1)
        proposed = self._item(99, target, 1)
        assumptions = (
            SensitivityAssumption("low", 0.5, 0.2),
            SensitivityAssumption("median", 1.0, 0.6),
            SensitivityAssumption("high", 1.5, 0.2),
        )
        result = analyze_clarification_value(self._snapshot(), proposed, target, assumptions)
        self.assertFalse(result.should_ask)
        self.assertIsNone(result.question)
        self.assertEqual("uncertainty_not_decision_material", result.reason_code)
        self.assertEqual(1.5, result.conservative_effort_hours)

    def test_deadline_and_split_sensitivity_are_material_even_if_top_date_is_stable(self):
        target = self.today
        proposed = self._item(99, target, 1, deadline=target)
        assumptions = (
            SensitivityAssumption("low", 1.0, 0.5),
            SensitivityAssumption("high", 5.0, 0.5),
        )
        result = analyze_clarification_value(self._snapshot(), proposed, target, assumptions)
        self.assertTrue(result.should_ask)
        self.assertIn("hard_deadline_risk_changes", result.material_changes)
        self.assertIn("split_shape_changes", result.material_changes)

    def test_at_most_one_highest_value_question_and_no_question_without_resolvable_field(self):
        target = self.today
        proposed = self._item(99, target, 1, deadline=target)
        assumptions = (
            SensitivityAssumption("low", 1.0, 0.5, ("effort_hours", "deliverable_quantity"), 500),
            SensitivityAssumption("high", 5.0, 0.5, ("effort_hours", "deliverable_quantity"), 2000),
        )
        result = analyze_clarification_value(
            self._snapshot(),
            proposed,
            target,
            assumptions,
            unresolved_fields=("effort_hours", "deliverable_quantity"),
            deliverable_unit="words",
        )
        self.assertTrue(result.should_ask)
        self.assertEqual("deliverable_quantity", result.unresolved_field)
        self.assertIn("words", result.question)

        unavailable = analyze_clarification_value(
            self._snapshot(),
            proposed,
            target,
            assumptions,
            unresolved_fields=(),
        )
        self.assertFalse(unavailable.should_ask)
        self.assertEqual("no_resolvable_question", unavailable.reason_code)

    def test_input_bounds_and_determinism(self):
        target = self.today + timedelta(days=1)
        proposed = self._item(99, target, 1)
        assumptions = (
            SensitivityAssumption("low", 0.5, 1),
            SensitivityAssumption("high", 3.0, 1),
        )
        snapshot = self._snapshot()
        first = analyze_clarification_value(snapshot, proposed, target, assumptions).to_dict()
        second = analyze_clarification_value(snapshot, proposed, target, assumptions).to_dict()
        self.assertEqual(first, second)
        with self.assertRaises(ValueError):
            analyze_clarification_value(snapshot, proposed, target, (SensitivityAssumption("only", 1, 1),))
        with self.assertRaises(ValueError):
            analyze_clarification_value(snapshot, proposed, target, (
                SensitivityAssumption("low", -1, 1),
                SensitivityAssumption("high", 2, 1),
            ))

    def test_zero_available_deadline_capacity_uses_bounded_json_safe_risk(self):
        target = self.today
        zero_policy = replace(self.policy, default_capacity_hours=0)
        snapshot = replace(self._snapshot(), preferences=zero_policy)
        proposed = self._item(99, target, 1, deadline=target)
        result = analyze_clarification_value(snapshot, proposed, target, (
            SensitivityAssumption("low", 1, 0.5),
            SensitivityAssumption("high", 2, 0.5),
        ))
        self.assertTrue(all(item.deadline_risk_band == "critical" for item in result.scenario_outcomes))
        self.assertTrue(all(item.deadline_risk_ratio is None for item in result.scenario_outcomes))


if __name__ == "__main__":
    unittest.main()
