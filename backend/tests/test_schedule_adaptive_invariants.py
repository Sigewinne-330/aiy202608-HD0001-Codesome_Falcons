import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_adaptive_ranking import (  # noqa: E402
    AdaptiveRankingPolicy,
    LearnedCandidateSignal,
    SafeCandidateSnapshot,
    apply_bounded_ranking,
)


class ScheduleAdaptiveInvariantTests(unittest.TestCase):
    def test_randomized_safe_candidates_preserve_set_rank_bound_and_hard_proof(self):
        randomizer = random.Random(20260805)
        policy = AdaptiveRankingPolicy(maximum_score_adjustment=0.25, maximum_rank_displacement=1)
        for trial in range(200):
            candidates = tuple(SafeCandidateSnapshot(
                candidate_id=f"trial-{trial}-{rank}",
                local_date=date(2026, 8, 5) + timedelta(days=rank),
                deterministic_score=float(rank) / 10 + randomizer.uniform(-0.02, 0.02),
                baseline_rank=rank,
                reason_codes=("capacity_safe",),
                hard_constraint_proof=("capacity", "deadline", "dependency"),
                effort_minutes=randomizer.randint(20, 240),
                deadline_critical=randomizer.random() < 0.1,
            ) for rank in range(1, 7))
            signals = tuple(LearnedCandidateSignal(
                item.candidate_id, randomizer.uniform(-100, 100), "model.v1", 1, 1, 20,
            ) for item in candidates)
            result = apply_bounded_ranking(candidates, signals, policy=policy, display_personalized=True)
            self.assertEqual(set(result.baseline_order), set(result.display_order))
            self.assertEqual(result.baseline_order, tuple(item.candidate_id for item in candidates) if not result.display_order else result.baseline_order)
            self.assertTrue(all(item.hard_feasible and item.hard_constraint_proof for item in result.safe_candidates))
            self.assertTrue(all(abs(item.applied_adjustment) <= policy.maximum_score_adjustment for item in result.annotations))
            self.assertTrue(all(abs(item.personalized_rank - item.baseline_rank) <= 1 for item in result.annotations))
            self.assertFalse(any(item.candidate_id not in result.baseline_order for item in result.annotations))


if __name__ == "__main__":
    unittest.main()
