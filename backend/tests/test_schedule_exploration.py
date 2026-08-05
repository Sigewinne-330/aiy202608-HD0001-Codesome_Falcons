import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_adaptive_ranking import (  # noqa: E402
    LearnedCandidateSignal,
    SafeCandidateSnapshot,
    apply_bounded_ranking,
)
from services.schedule_exploration import assign_near_tie_display  # noqa: E402


class ScheduleExplorationTests(unittest.TestCase):
    def _fixture(self, *, critical=False, count=2):
        candidates = tuple(SafeCandidateSnapshot(
            candidate_id=f"c{index}",
            local_date=date(2026, 8, 5) + timedelta(days=index),
            deterministic_score=1 + 0.02 * index,
            baseline_rank=index,
            reason_codes=("safe",),
            hard_constraint_proof=("hard",),
            effort_minutes=60,
            deadline_critical=critical,
        ) for index in range(1, count + 1))
        signals = tuple(LearnedCandidateSignal(
            candidate_id=item.candidate_id,
            raw_adjustment=0,
            model_version="v1",
            maturity=1,
            calibration_factor=1,
            eligible_decision_count=25,
        ) for item in candidates)
        return candidates, apply_bounded_ranking(candidates, signals)

    def test_exact_probability_and_seeded_distribution(self):
        candidates, ranking = self._fixture()
        counts = {ranking.baseline_order: 0, tuple(reversed(ranking.baseline_order)): 0}
        source = random.Random(20260805)
        for _ in range(600):
            assignment = assign_near_tie_display(
                candidates,
                ranking,
                enabled=True,
                consent_enabled=True,
                near_tie_score_delta=0.1,
                random_source=source,
            )
            self.assertTrue(assignment.randomized)
            self.assertEqual(0.5, assignment.assignment_probability)
            self.assertEqual(set(ranking.baseline_order), set(assignment.display_order))
            counts[assignment.display_order] += 1
        self.assertTrue(all(240 <= count <= 360 for count in counts.values()))

    def test_consent_runtime_urgent_unique_and_low_maturity_exclusions(self):
        candidates, ranking = self._fixture()
        cases = (
            {"enabled": False, "consent_enabled": True},
            {"enabled": True, "consent_enabled": False},
        )
        for values in cases:
            assignment = assign_near_tie_display(
                candidates, ranking, near_tie_score_delta=0.1, **values
            )
            self.assertFalse(assignment.randomized)
            self.assertIsNone(assignment.assignment_probability)
        critical, critical_ranking = self._fixture(critical=True)
        self.assertFalse(assign_near_tie_display(
            critical, critical_ranking, enabled=True, consent_enabled=True, near_tie_score_delta=0.1
        ).randomized)
        unique, unique_ranking = self._fixture(count=1)
        self.assertEqual("unique_candidate", assign_near_tie_display(
            unique, unique_ranking, enabled=True, consent_enabled=True, near_tie_score_delta=0.1
        ).exclusion_reason)

        low_signals = tuple(LearnedCandidateSignal(
            item.candidate_id, 0, "v1", 0.2, 1, 25
        ) for item in candidates)
        low_ranking = apply_bounded_ranking(candidates, low_signals)
        self.assertFalse(assign_near_tie_display(
            candidates, low_ranking, enabled=True, consent_enabled=True, near_tie_score_delta=0.1
        ).randomized)


if __name__ == "__main__":
    unittest.main()
