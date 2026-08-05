import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_model_evaluation import (  # noqa: E402
    EffortEvaluationPoint,
    OperationalEvaluationPoint,
    RankingEvaluationPoint,
    RiskEvaluationPoint,
    TemporalEvaluationError,
    evaluate_temporal_models,
)


class ScheduleModelEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.training_end = datetime(2026, 7, 31)
        self.evaluation_end = datetime(2026, 8, 31)

    def _effort(self, index, *, subject="Economics", archetype="essay_draft"):
        decision = self.training_end + timedelta(days=index + 1)
        return EffortEvaluationPoint(
            decision_at=decision,
            feature_as_of=decision - timedelta(minutes=1),
            outcome_at=decision + timedelta(days=1),
            predicted_p50_minutes=100,
            predicted_p90_minutes=150,
            actual_minutes=100 if index % 2 == 0 else 120,
            subject=subject,
            task_archetype=archetype,
        )

    def _risk(self, index, probability, outcome):
        decision = self.training_end + timedelta(days=index + 1)
        return RiskEvaluationPoint(
            decision_at=decision,
            feature_as_of=decision,
            outcome_at=decision + timedelta(days=1),
            completion_probability=probability,
            completed_before_deadline=outcome,
            subject="Economics",
            task_archetype="essay_draft",
            deadline_critical=True,
        )

    def test_known_future_only_metrics_and_required_slices(self):
        effort = [self._effort(index) for index in range(5)]
        risk = [self._risk(5 + index, probability, outcome) for index, (probability, outcome) in enumerate(
            ((0.9, True), (0.8, True), (0.2, False), (0.1, False), (0.7, True))
        )]
        ranking = [RankingEvaluationPoint(
            decision_at=self.training_end + timedelta(days=1), baseline_rank=2, learned_rank=1
        )]
        operations = [
            OperationalEvaluationPoint(self.training_end + timedelta(days=1), 10, False),
            OperationalEvaluationPoint(self.training_end + timedelta(days=2), 20, True, True),
        ]
        report = evaluate_temporal_models(
            training_end=self.training_end,
            evaluation_end=self.evaluation_end,
            effort_points=effort,
            risk_points=risk,
            ranking_points=ranking,
            operational_points=operations,
            required_slices=("subject:Economics", "task_archetype:essay_draft"),
            minimum_slice_n=5,
        )
        self.assertEqual(5, report.effort_metrics["n"])
        self.assertEqual(1.0, report.effort_metrics["p90_coverage"])
        self.assertAlmostEqual(0.038, report.risk_metrics["brier_score"])
        self.assertEqual(1.0, report.risk_metrics["deadline_risk_recall"])
        self.assertTrue(report.ranking_metrics["deterministic_invariants_passed"])
        self.assertEqual(20, report.operational_metrics["p95_latency_ms"])
        self.assertEqual(0.5, report.operational_metrics["fallback_rate"])
        self.assertTrue(report.required_slices_present)
        self.assertTrue(report.leakage_checks_passed)

    def test_future_feature_and_nonfuture_split_are_rejected(self):
        point = self._effort(0)
        leaked = EffortEvaluationPoint(
            **{**point.__dict__, "feature_as_of": point.decision_at + timedelta(seconds=1)}
        )
        with self.assertRaises(TemporalEvaluationError):
            evaluate_temporal_models(
                training_end=self.training_end,
                evaluation_end=self.evaluation_end,
                effort_points=[leaked],
            )
        old = EffortEvaluationPoint(
            **{**point.__dict__, "decision_at": self.training_end}
        )
        with self.assertRaises(TemporalEvaluationError):
            evaluate_temporal_models(
                training_end=self.training_end,
                evaluation_end=self.evaluation_end,
                effort_points=[old],
            )

    def test_missing_required_slice_and_invariant_failure_are_explicit(self):
        report = evaluate_temporal_models(
            training_end=self.training_end,
            evaluation_end=self.evaluation_end,
            effort_points=[self._effort(0)],
            ranking_points=[RankingEvaluationPoint(
                decision_at=self.training_end + timedelta(days=1),
                baseline_rank=1,
                learned_rank=1,
                hard_constraint_violation=True,
                learned_auto_applied=True,
            )],
            required_slices=("subject:Mathematics",),
            minimum_slice_n=5,
        )
        self.assertFalse(report.required_slices_present)
        self.assertFalse(report.ranking_metrics["deterministic_invariants_passed"])
        self.assertEqual(1, report.ranking_metrics["hard_constraint_violations"])


if __name__ == "__main__":
    unittest.main()
