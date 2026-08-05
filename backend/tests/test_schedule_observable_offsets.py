import math
import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_observable_offsets import (  # noqa: E402
    ContextOutcome,
    WeightedObservable,
    derive_observable_offsets,
)


class ScheduleObservableOffsetTests(unittest.TestCase):
    def test_sparse_context_comparisons_fall_back_to_zero(self):
        result = derive_observable_offsets(
            eligible_personal=True,
            context_outcomes=(
                ContextOutcome(1.2, 4, 0),
                ContextOutcome(0.9, 1, 4),
            ),
        )
        self.assertEqual(0, result.factor("same_kind_saturation").offset)
        self.assertEqual("insufficient_comparison", result.factor("same_kind_saturation").status)
        self.assertEqual(0, result.factor("switching_sensitivity").offset)

    def test_repeated_observable_evidence_produces_separate_bounded_factors(self):
        contexts = tuple(
            [ContextOutcome(1.5, 4, 0) for _ in range(5)]
            + [ContextOutcome(0.9, 1, 0) for _ in range(5)]
            + [ContextOutcome(1.6, 1, 4) for _ in range(5)]
        )
        result = derive_observable_offsets(
            eligible_personal=True,
            duration_overrun_ratios=tuple(WeightedObservable(1.8) for _ in range(5)),
            initiation_delay_minutes=tuple(WeightedObservable(180) for _ in range(5)),
            deferral_counts=tuple(WeightedObservable(3) for _ in range(5)),
            optional_exertion_ratings=tuple(WeightedObservable(4) for _ in range(5)),
            context_outcomes=contexts,
        )
        self.assertGreater(result.factor("duration_overrun").offset, 0)
        self.assertGreater(result.factor("initiation_delay").offset, 0)
        self.assertGreater(result.factor("same_kind_saturation").offset, 0)
        self.assertGreater(result.factor("switching_sensitivity").offset, 0)
        payload = result.to_dict()
        self.assertIsNone(payload["latent_trait_score"])
        self.assertNotIn("motivation", {item["name"] for item in payload["factors"]})

    def test_consent_gate_zeros_all_offsets_even_with_evidence(self):
        result = derive_observable_offsets(
            eligible_personal=False,
            duration_overrun_ratios=tuple(WeightedObservable(10) for _ in range(20)),
        )
        self.assertTrue(all(item.offset == 0 for item in result.factors))
        self.assertTrue(all(item.status != "eligible" for item in result.factors))

    def test_maximum_influence_properties_hold_at_extremes(self):
        contexts = tuple(
            [ContextOutcome(20, 100, 100) for _ in range(10)]
            + [ContextOutcome(0.05, 0, 0) for _ in range(10)]
        )
        result = derive_observable_offsets(
            eligible_personal=True,
            duration_overrun_ratios=tuple(WeightedObservable(20) for _ in range(10)),
            initiation_delay_minutes=tuple(WeightedObservable(100_800) for _ in range(10)),
            deferral_counts=tuple(WeightedObservable(100) for _ in range(10)),
            optional_exertion_ratings=tuple(WeightedObservable(5) for _ in range(10)),
            context_outcomes=contexts,
        )
        for factor in result.factors:
            self.assertTrue(math.isfinite(factor.offset))
            self.assertGreaterEqual(factor.offset, factor.lower_bound)
            self.assertLessEqual(factor.offset, factor.upper_bound)
            self.assertLessEqual(factor.effective_sample_size, factor.evidence_count)

    def test_invalid_observations_and_thresholds_are_rejected(self):
        with self.assertRaises(ValueError):
            derive_observable_offsets(
                eligible_personal=True,
                duration_overrun_ratios=(WeightedObservable(float("nan")),),
            )
        with self.assertRaises(ValueError):
            derive_observable_offsets(eligible_personal=True, minimum_effective_n=0)


if __name__ == "__main__":
    unittest.main()
