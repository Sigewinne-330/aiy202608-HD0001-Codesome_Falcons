import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_drift import (  # noqa: E402
    ResidualObservation,
    TemporaryContext,
    compute_adaptive_influence,
    detect_sustained_drift,
)


class ScheduleDriftTests(unittest.TestCase):
    def setUp(self):
        self.reference = date(2026, 8, 5)

    def _baseline(self):
        return [
            ResidualObservation(self.reference - timedelta(days=60 + index), 0.02)
            for index in range(8)
        ]

    def test_isolated_miss_does_not_trigger_drift(self):
        values = self._baseline() + [ResidualObservation(self.reference, 1.0)]
        result = detect_sustained_drift(values, reference_date=self.reference)
        self.assertEqual("stable", result.state)
        self.assertEqual("insufficient_sustained_evidence", result.reason)

    def test_sustained_change_triggers_drift_and_recovery_is_gradual(self):
        changed = self._baseline() + [
            ResidualObservation(self.reference - timedelta(days=index), 0.65)
            for index in range(7)
        ]
        drifted = detect_sustained_drift(changed, reference_date=self.reference)
        self.assertEqual("drifted", drifted.state)
        self.assertGreater(abs(drifted.residual_shift), 0.35)

        recovered = self._baseline() + [
            ResidualObservation(self.reference - timedelta(days=index), 0.03)
            for index in range(7)
        ]
        recovery = detect_sustained_drift(recovered, reference_date=self.reference, prior_state="drifted")
        self.assertEqual("recovering", recovery.state)

    def test_long_absence_decays_personal_influence_toward_prior(self):
        fresh = compute_adaptive_influence(
            reference_date=self.reference,
            latest_evidence_date=self.reference - timedelta(days=10),
            drift_state="stable",
        )
        aging = compute_adaptive_influence(
            reference_date=self.reference,
            latest_evidence_date=self.reference - timedelta(days=120),
            drift_state="stable",
        )
        absent = compute_adaptive_influence(
            reference_date=self.reference,
            latest_evidence_date=self.reference - timedelta(days=400),
            drift_state="stable",
        )
        self.assertEqual(1, fresh.personal_multiplier)
        self.assertGreater(fresh.personal_multiplier, aging.personal_multiplier)
        self.assertEqual(0, absent.personal_multiplier)

    def test_exam_week_context_is_bounded_temporary_and_does_not_rewrite_drift(self):
        context = TemporaryContext(
            valid_from=self.reference - timedelta(days=2),
            valid_until=self.reference + timedelta(days=5),
            effort_multiplier=1.2,
        )
        active = compute_adaptive_influence(
            reference_date=self.reference,
            latest_evidence_date=self.reference,
            drift_state="stable",
            temporary_context=context,
        )
        expired = compute_adaptive_influence(
            reference_date=self.reference + timedelta(days=10),
            latest_evidence_date=self.reference,
            drift_state="stable",
            temporary_context=context,
        )
        self.assertTrue(active.context_active)
        self.assertEqual(1.2, active.context_effort_multiplier)
        self.assertEqual(1.0, active.drift_multiplier)
        self.assertFalse(expired.context_active)
        self.assertEqual(1.0, expired.context_effort_multiplier)

    def test_new_term_context_stays_temporal_without_fabricating_drift(self):
        context = TemporaryContext(
            valid_from=self.reference,
            valid_until=self.reference + timedelta(days=30),
            effort_multiplier=0.9,
        )
        influence = compute_adaptive_influence(
            reference_date=self.reference,
            latest_evidence_date=self.reference - timedelta(days=20),
            drift_state="stable",
            temporary_context=context,
        )
        assessment = detect_sustained_drift(
            self._baseline(),
            reference_date=self.reference,
        )
        self.assertEqual("stable", assessment.state)
        self.assertTrue(influence.context_active)
        self.assertEqual(0.9, influence.context_effort_multiplier)

    def test_watch_and_drift_reduce_influence_without_unbounded_change(self):
        stable = compute_adaptive_influence(
            reference_date=self.reference, latest_evidence_date=self.reference, drift_state="stable"
        )
        watch = compute_adaptive_influence(
            reference_date=self.reference, latest_evidence_date=self.reference, drift_state="watch"
        )
        drifted = compute_adaptive_influence(
            reference_date=self.reference, latest_evidence_date=self.reference, drift_state="drifted"
        )
        self.assertGreater(stable.personal_multiplier, watch.personal_multiplier)
        self.assertGreater(watch.personal_multiplier, drifted.personal_multiplier)
        self.assertGreaterEqual(drifted.personal_multiplier, 0)


if __name__ == "__main__":
    unittest.main()
