import dataclasses
from datetime import date, timedelta
import ast
import inspect
import random
import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import schedule_adaptive_ranking as module  # noqa: E402
from services.schedule_adaptive_ranking import (  # noqa: E402
    AdaptiveRankingError,
    AdaptiveRankingPolicy,
    LearnedCandidateSignal,
    SafeCandidateSnapshot,
    annotate_safe_candidates,
    apply_bounded_ranking,
)


class ScheduleAdaptiveRankingBoundaryTests(unittest.TestCase):
    def _candidate(self, rank, *, feasible=True, candidate_id=None):
        return SafeCandidateSnapshot(
            candidate_id=candidate_id or f"date:2026-08-{5 + rank:02d}",
            local_date=date(2026, 8, 5) + timedelta(days=rank),
            deterministic_score=float(rank),
            baseline_rank=rank,
            reason_codes=("capacity_safe",),
            hard_constraint_proof=("deadline", "dependencies", "capacity"),
            effort_minutes=60,
            hard_feasible=feasible,
        )

    def test_adapter_module_has_no_persistence_or_mutation_dependencies(self):
        source = inspect.getsource(module)
        imported_modules = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        forbidden_imports = {"models", "sqlalchemy", "services.schedule_lifecycle", "services.schedule_engine"}
        for marker in forbidden_imports:
            with self.subTest(marker=marker):
                self.assertFalse(any(name == marker or name.startswith(f"{marker}.") for name in imported_modules))

    def test_infeasible_candidate_and_missing_proof_are_rejected(self):
        with self.assertRaises(AdaptiveRankingError):
            self._candidate(1, feasible=False)
        with self.assertRaises(AdaptiveRankingError):
            SafeCandidateSnapshot(
                candidate_id="unsafe",
                local_date=date(2026, 8, 5),
                deterministic_score=1,
                baseline_rank=1,
                reason_codes=(),
                hard_constraint_proof=(),
                effort_minutes=60,
            )

    def test_unknown_learned_candidate_cannot_be_added(self):
        with self.assertRaises(AdaptiveRankingError):
            annotate_safe_candidates(
                (self._candidate(1),),
                (LearnedCandidateSignal(
                    candidate_id="invented",
                    raw_adjustment=-999,
                    model_version="reranker.v1",
                    maturity=1,
                    calibration_factor=1,
                ),),
            )

    def test_annotation_preserves_all_candidates_hard_fields_and_baseline_order(self):
        candidates = (self._candidate(1), self._candidate(2), self._candidate(3))
        before = tuple(dataclasses.asdict(item) for item in candidates)
        signals = tuple(LearnedCandidateSignal(
            candidate_id=item.candidate_id,
            raw_adjustment=-100 if item.baseline_rank == 3 else 100,
            model_version="reranker.v1",
            maturity=1,
            calibration_factor=1,
            evidence_categories=("recent_decisions",),
        ) for item in candidates)
        result = annotate_safe_candidates(candidates, signals)
        after = tuple(dataclasses.asdict(item) for item in result.safe_candidates)
        self.assertEqual(before, after)
        self.assertEqual(tuple(item.candidate_id for item in candidates), result.baseline_order)
        self.assertEqual(result.baseline_order, result.display_order)
        self.assertTrue(result.hard_fields_unchanged)
        self.assertTrue(all(item.applied_adjustment == 0 for item in result.annotations))
        self.assertTrue(all(item.personalized_rank == item.baseline_rank for item in result.annotations))

    def test_inputs_outputs_and_annotation_map_are_immutable(self):
        candidate = self._candidate(1)
        result = annotate_safe_candidates((candidate,))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.local_date = date(2030, 1, 1)
        with self.assertRaises(TypeError):
            result.annotations_by_id["new"] = result.annotations[0]

    def test_twenty_decision_maturity_and_calibration_gates_are_all_required(self):
        candidates = (
            self._candidate(1),
            SafeCandidateSnapshot(
                candidate_id="near-tie",
                local_date=date(2026, 8, 7),
                deterministic_score=1.05,
                baseline_rank=2,
                reason_codes=("capacity_safe",),
                hard_constraint_proof=("deadline", "capacity"),
                effort_minutes=60,
            ),
        )
        cases = (
            {"eligible_decision_count": 19, "maturity": 1.0, "calibration_factor": 1.0},
            {"eligible_decision_count": 20, "maturity": 0.49, "calibration_factor": 1.0},
            {"eligible_decision_count": 20, "maturity": 1.0, "calibration_factor": 0.59},
        )
        for values in cases:
            with self.subTest(values=values):
                signals = tuple(LearnedCandidateSignal(
                    candidate_id=item.candidate_id,
                    raw_adjustment=1 if item.baseline_rank == 1 else -1,
                    model_version="reranker.v1",
                    **values,
                ) for item in candidates)
                result = apply_bounded_ranking(candidates, signals, display_personalized=True)
                self.assertEqual(result.baseline_order, result.display_order)
                self.assertTrue(all(item.applied_adjustment == 0 for item in result.annotations))

    def test_near_tie_scaling_reorders_only_within_all_bounds(self):
        candidates = (
            SafeCandidateSnapshot("a", date(2026, 8, 6), 1.0, 1, ("safe",), ("hard",), 60),
            SafeCandidateSnapshot("b", date(2026, 8, 7), 1.05, 2, ("safe",), ("hard",), 60),
            SafeCandidateSnapshot("c", date(2026, 8, 8), 3.0, 3, ("safe",), ("hard",), 60),
        )
        signals = (
            LearnedCandidateSignal("a", 10, "v1", 1, 1, 20),
            LearnedCandidateSignal("b", -10, "v1", 1, 1, 20),
            LearnedCandidateSignal("c", -10, "v1", 1, 1, 20),
        )
        policy = AdaptiveRankingPolicy(
            serving_safety_budget=0.5,
            maximum_score_adjustment=0.25,
            maximum_rank_displacement=1,
            near_tie_score_delta=0.1,
        )
        result = apply_bounded_ranking(candidates, signals, policy=policy, display_personalized=True)
        self.assertEqual(("b", "a", "c"), result.display_order)
        self.assertTrue(all(abs(item.applied_adjustment) <= 0.125 for item in result.annotations))
        self.assertEqual(0, result.annotations_by_id["c"].applied_adjustment)
        self.assertEqual(3, result.annotations_by_id["c"].personalized_rank)

    def test_seeded_property_never_exceeds_adjustment_or_displacement(self):
        randomizer = random.Random(20260805)
        policy = AdaptiveRankingPolicy(maximum_score_adjustment=0.2, maximum_rank_displacement=1)
        for iteration in range(100):
            scores = sorted(randomizer.uniform(0, 1) for _ in range(6))
            candidates = tuple(SafeCandidateSnapshot(
                candidate_id=f"{iteration}:{rank}",
                local_date=date(2026, 8, 5) + timedelta(days=rank),
                deterministic_score=score,
                baseline_rank=rank,
                reason_codes=("safe",),
                hard_constraint_proof=("hard",),
                effort_minutes=60,
                deadline_critical=randomizer.random() < 0.1,
            ) for rank, score in enumerate(scores, start=1))
            signals = tuple(LearnedCandidateSignal(
                item.candidate_id,
                randomizer.uniform(-5, 5),
                "v1",
                randomizer.random(),
                randomizer.random(),
                randomizer.randint(0, 50),
            ) for item in candidates)
            result = apply_bounded_ranking(candidates, signals, policy=policy, display_personalized=True)
            self.assertEqual(set(result.baseline_order), set(result.display_order))
            for item in result.annotations:
                self.assertLessEqual(abs(item.applied_adjustment), policy.maximum_score_adjustment)
                self.assertLessEqual(abs(item.personalized_rank - item.baseline_rank), 1)


if __name__ == "__main__":
    unittest.main()
