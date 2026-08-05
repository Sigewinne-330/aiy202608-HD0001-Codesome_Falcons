import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_promotion_gates import evaluate_promotion_gates  # noqa: E402


class SchedulePromotionGateTests(unittest.TestCase):
    def setUp(self):
        self.baseline = {
            "deadline_miss_rate": 0.10,
            "brier_score": 0.12,
            "overload_exposure_rate": 0.20,
        }
        self.candidate = {
            "hard_constraint_violations": 0,
            "learned_auto_apply": 0,
            "candidate_set_changes": 0,
            "effort_conservation_changes": 0,
            "cross_user_leakage_count": 0,
            "ineligible_evidence_served_count": 0,
            "deadline_miss_rate": 0.09,
            "deadline_risk_recall": 0.90,
            "effort_p90_coverage": 0.85,
            "risk_ece": 0.06,
            "brier_score": 0.10,
            "overload_exposure_rate": 0.18,
            "movement_rate": 0.10,
            "rejection_rate": 0.20,
            "undo_rate": 0.05,
            "false_intervention_rate": 0.05,
            "deletion_correctness_rate": 1.0,
            "deleted_evidence_served_count": 0,
            "maximum_slice_disparity_gap": 0.08,
            "required_slices_present": True,
            "p95_latency_ms": 40,
            "fallback_rate": 0.01,
            "raw_completion_rate": 0.99,
        }

    def test_all_layers_pass_and_raw_completion_is_explicitly_ignored(self):
        decision = evaluate_promotion_gates(candidate=self.candidate, baseline=self.baseline)
        self.assertTrue(decision.approved)
        self.assertEqual(8, len(decision.passed_layers))
        self.assertIn("raw_completion_rate", decision.ignored_metrics)

    def test_every_guardrail_blocks_even_with_high_raw_completion(self):
        cases = {
            "hard_constraint_violations": (1, "safety_violation:hard_constraint_violations"),
            "deadline_miss_rate": (0.11, "deadline_reliability_degraded"),
            "risk_ece": (0.11, "risk_calibration_below_gate"),
            "overload_exposure_rate": (0.21, "overload_exposure_degraded"),
            "rejection_rate": (0.51, "autonomy_burden:rejection_rate"),
            "deletion_correctness_rate": (0.99, "deletion_correctness_failed"),
            "maximum_slice_disparity_gap": (0.16, "slice_disparity_above_gate"),
            "p95_latency_ms": (76, "latency_above_gate"),
        }
        for key, (value, blocker) in cases.items():
            with self.subTest(key=key):
                candidate = {**self.candidate, key: value, "raw_completion_rate": 1.0}
                decision = evaluate_promotion_gates(candidate=candidate, baseline=self.baseline)
                self.assertFalse(decision.approved)
                self.assertIn(blocker, decision.blockers)

    def test_missing_metric_fails_closed_and_point_gain_cannot_trade_calibration(self):
        missing = dict(self.candidate)
        missing.pop("deleted_evidence_served_count")
        self.assertIn(
            "missing_deletion_metric",
            evaluate_promotion_gates(candidate=missing, baseline=self.baseline).blockers,
        )
        point_better = {
            **self.candidate,
            "median_absolute_log_error": 0.01,
            "effort_p90_coverage": 0.50,
        }
        decision = evaluate_promotion_gates(candidate=point_better, baseline=self.baseline)
        self.assertFalse(decision.approved)
        self.assertIn("effort_interval_coverage_below_gate", decision.blockers)


if __name__ == "__main__":
    unittest.main()
