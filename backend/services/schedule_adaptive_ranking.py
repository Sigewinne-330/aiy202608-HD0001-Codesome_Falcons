"""Pure annotation boundary over immutable deterministic-safe candidates.

This module intentionally has no database, repository, lifecycle, or scheduler
imports.  It cannot create, move, apply, or persist work.  The deterministic
scheduler remains the sole producer and feasibility authority for candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional


ADAPTIVE_RANKING_SCHEMA_VERSION = "scheduling-adaptive-ranking.v1"


class AdaptiveRankingError(ValueError):
    """A candidate boundary or learned annotation violated safety rules."""


def _finite(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AdaptiveRankingError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise AdaptiveRankingError(f"{field} must be finite")
    return parsed


@dataclass(frozen=True)
class SafeCandidateSnapshot:
    candidate_id: str
    local_date: date
    deterministic_score: float
    baseline_rank: int
    reason_codes: tuple[str, ...]
    hard_constraint_proof: tuple[str, ...]
    effort_minutes: int
    deadline_critical: bool = False
    hard_feasible: bool = True

    def __post_init__(self) -> None:
        if not self.candidate_id or len(self.candidate_id) > 128:
            raise AdaptiveRankingError("candidate_id is required and bounded")
        if not isinstance(self.local_date, date):
            raise AdaptiveRankingError("candidate date is required")
        object.__setattr__(self, "deterministic_score", _finite(self.deterministic_score, "deterministic_score"))
        if not 1 <= self.baseline_rank <= 100:
            raise AdaptiveRankingError("baseline_rank must be between 1 and 100")
        if not self.hard_feasible:
            raise AdaptiveRankingError("personalization cannot receive an infeasible candidate")
        if not self.hard_constraint_proof:
            raise AdaptiveRankingError("deterministic hard-constraint proof is required")
        if not 1 <= self.effort_minutes <= 100_800:
            raise AdaptiveRankingError("candidate effort is out of bounds")
        if len(self.reason_codes) > 32 or len(self.hard_constraint_proof) > 32:
            raise AdaptiveRankingError("candidate evidence is oversized")
        for value in (*self.reason_codes, *self.hard_constraint_proof):
            if not isinstance(value, str) or not value or len(value) > 96:
                raise AdaptiveRankingError("candidate evidence codes must be bounded strings")


@dataclass(frozen=True)
class LearnedCandidateSignal:
    candidate_id: str
    raw_adjustment: float
    model_version: Optional[str]
    maturity: float
    calibration_factor: float
    eligible_decision_count: int = 0
    evidence_categories: tuple[str, ...] = ()
    estimate_p50_minutes: Optional[int] = None
    estimate_p90_minutes: Optional[int] = None
    completion_probability: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.candidate_id or len(self.candidate_id) > 128:
            raise AdaptiveRankingError("signal candidate_id is required and bounded")
        object.__setattr__(self, "raw_adjustment", _finite(self.raw_adjustment, "raw_adjustment"))
        for field in ("maturity", "calibration_factor"):
            value = _finite(getattr(self, field), field)
            if not 0 <= value <= 1:
                raise AdaptiveRankingError(f"{field} must be within [0, 1]")
            object.__setattr__(self, field, value)
        if not 0 <= self.eligible_decision_count <= 1_000_000:
            raise AdaptiveRankingError("eligible_decision_count is out of bounds")
        if self.model_version is not None and (not self.model_version or len(self.model_version) > 128):
            raise AdaptiveRankingError("model_version is invalid")
        if len(self.evidence_categories) > 12:
            raise AdaptiveRankingError("too many evidence categories")
        if any(not item or len(item) > 64 for item in self.evidence_categories):
            raise AdaptiveRankingError("evidence categories must be bounded strings")
        if self.estimate_p50_minutes is not None and not 1 <= self.estimate_p50_minutes <= 100_800:
            raise AdaptiveRankingError("P50 estimate is out of bounds")
        if self.estimate_p90_minutes is not None and not 1 <= self.estimate_p90_minutes <= 100_800:
            raise AdaptiveRankingError("P90 estimate is out of bounds")
        if (
            self.estimate_p50_minutes is not None
            and self.estimate_p90_minutes is not None
            and self.estimate_p50_minutes > self.estimate_p90_minutes
        ):
            raise AdaptiveRankingError("P50 estimate cannot exceed P90")
        if self.completion_probability is not None:
            probability = _finite(self.completion_probability, "completion_probability")
            if not 0 <= probability <= 1:
                raise AdaptiveRankingError("completion_probability must be within [0, 1]")
            object.__setattr__(self, "completion_probability", probability)


@dataclass(frozen=True)
class CandidateAnnotation:
    candidate_id: str
    baseline_rank: int
    deterministic_score: float
    raw_adjustment: float
    applied_adjustment: float
    personalized_score: float
    personalized_rank: int
    model_version: Optional[str]
    maturity: float
    calibration_factor: float
    evidence_categories: tuple[str, ...]
    estimate_p50_minutes: Optional[int]
    estimate_p90_minutes: Optional[int]
    completion_probability: Optional[float]


@dataclass(frozen=True)
class AdaptiveRankingResult:
    schema_version: str
    safe_candidates: tuple[SafeCandidateSnapshot, ...]
    annotations: tuple[CandidateAnnotation, ...]
    baseline_order: tuple[str, ...]
    display_order: tuple[str, ...]
    hard_fields_unchanged: bool
    fallback_reason: Optional[str]

    @property
    def annotations_by_id(self) -> Mapping[str, CandidateAnnotation]:
        return MappingProxyType({item.candidate_id: item for item in self.annotations})


@dataclass(frozen=True)
class AdaptiveRankingPolicy:
    minimum_eligible_decisions: int = 20
    minimum_maturity: float = 0.5
    minimum_calibration_factor: float = 0.6
    serving_safety_budget: float = 0.5
    maximum_score_adjustment: float = 0.25
    maximum_rank_displacement: int = 1
    near_tie_score_delta: float = 0.10

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_eligible_decisions <= 1_000_000:
            raise AdaptiveRankingError("minimum decision gate is out of bounds")
        for field in ("minimum_maturity", "minimum_calibration_factor", "serving_safety_budget"):
            value = _finite(getattr(self, field), field)
            if not 0 <= value <= 1:
                raise AdaptiveRankingError(f"{field} must be within [0, 1]")
            object.__setattr__(self, field, value)
        maximum = _finite(self.maximum_score_adjustment, "maximum_score_adjustment")
        if not 0 <= maximum <= 1:
            raise AdaptiveRankingError("maximum score adjustment is out of bounds")
        object.__setattr__(self, "maximum_score_adjustment", maximum)
        if not 0 <= self.maximum_rank_displacement <= 3:
            raise AdaptiveRankingError("maximum rank displacement is out of bounds")
        near_tie = _finite(self.near_tie_score_delta, "near_tie_score_delta")
        if not 0 <= near_tie <= 1:
            raise AdaptiveRankingError("near-tie delta is out of bounds")
        object.__setattr__(self, "near_tie_score_delta", near_tie)


def annotate_safe_candidates(
    candidates: Iterable[SafeCandidateSnapshot],
    signals: Iterable[LearnedCandidateSignal] = (),
) -> AdaptiveRankingResult:
    """Attach learned metadata while preserving exact deterministic authority.

    Ranking movement is intentionally disabled at this layer; bounded serving
    policy is added separately.  That separation makes this primitive safe for
    replay, shadow, corrupt-model fallback, and static mutation-boundary review.
    """
    safe = tuple(candidates)
    if not safe:
        return AdaptiveRankingResult(
            schema_version=ADAPTIVE_RANKING_SCHEMA_VERSION,
            safe_candidates=(),
            annotations=(),
            baseline_order=(),
            display_order=(),
            hard_fields_unchanged=True,
            fallback_reason="no_deterministic_candidates",
        )
    candidate_ids = [item.candidate_id for item in safe]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise AdaptiveRankingError("deterministic candidate IDs must be unique")
    ranks = [item.baseline_rank for item in safe]
    if sorted(ranks) != list(range(1, len(safe) + 1)):
        raise AdaptiveRankingError("baseline ranks must be contiguous and unique")
    baseline = tuple(item.candidate_id for item in sorted(safe, key=lambda item: item.baseline_rank))

    learned: dict[str, LearnedCandidateSignal] = {}
    for signal in signals:
        if signal.candidate_id not in candidate_ids:
            raise AdaptiveRankingError("learned code cannot introduce a candidate")
        if signal.candidate_id in learned:
            raise AdaptiveRankingError("duplicate learned signal")
        learned[signal.candidate_id] = signal

    annotations = []
    for candidate in sorted(safe, key=lambda item: item.baseline_rank):
        signal = learned.get(candidate.candidate_id)
        raw_adjustment = signal.raw_adjustment if signal else 0.0
        annotations.append(CandidateAnnotation(
            candidate_id=candidate.candidate_id,
            baseline_rank=candidate.baseline_rank,
            deterministic_score=candidate.deterministic_score,
            raw_adjustment=raw_adjustment,
            applied_adjustment=0.0,
            personalized_score=candidate.deterministic_score,
            personalized_rank=candidate.baseline_rank,
            model_version=signal.model_version if signal else None,
            maturity=signal.maturity if signal else 0.0,
            calibration_factor=signal.calibration_factor if signal else 0.0,
            evidence_categories=signal.evidence_categories if signal else (),
            estimate_p50_minutes=signal.estimate_p50_minutes if signal else None,
            estimate_p90_minutes=signal.estimate_p90_minutes if signal else None,
            completion_probability=signal.completion_probability if signal else None,
        ))
    return AdaptiveRankingResult(
        schema_version=ADAPTIVE_RANKING_SCHEMA_VERSION,
        safe_candidates=safe,
        annotations=tuple(annotations),
        baseline_order=baseline,
        display_order=baseline,
        hard_fields_unchanged=True,
        fallback_reason=None if learned else "no_learned_signals",
    )


def apply_bounded_ranking(
    candidates: Iterable[SafeCandidateSnapshot],
    signals: Iterable[LearnedCandidateSignal],
    *,
    policy: AdaptiveRankingPolicy = AdaptiveRankingPolicy(),
    display_personalized: bool = False,
) -> AdaptiveRankingResult:
    """Scale and rank only deterministic near ties within strict hard bounds."""
    safe = tuple(candidates)
    signal_tuple = tuple(signals)
    base = annotate_safe_candidates(safe, signal_tuple)
    by_signal = {item.candidate_id: item for item in signal_tuple}
    ordered_candidates = sorted(safe, key=lambda item: item.baseline_rank)

    # Form contiguous deterministic near-tie components. Deadline-critical
    # candidates are singleton barriers and can never move.
    groups: list[list[SafeCandidateSnapshot]] = []
    for candidate in ordered_candidates:
        if not groups:
            groups.append([candidate])
            continue
        previous = groups[-1][-1]
        near = abs(candidate.deterministic_score - previous.deterministic_score) <= policy.near_tie_score_delta
        if near and not candidate.deadline_critical and not previous.deadline_critical:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])

    applied: dict[str, float] = {}
    for group in groups:
        movable_group = len(group) > 1
        for candidate in group:
            signal = by_signal.get(candidate.candidate_id)
            gate_passed = bool(
                movable_group
                and not candidate.deadline_critical
                and signal is not None
                and signal.eligible_decision_count >= policy.minimum_eligible_decisions
                and signal.maturity >= policy.minimum_maturity
                and signal.calibration_factor >= policy.minimum_calibration_factor
                and policy.maximum_rank_displacement > 0
            )
            if not gate_passed:
                applied[candidate.candidate_id] = 0.0
                continue
            cap = (
                policy.maximum_score_adjustment
                * signal.maturity
                * signal.calibration_factor
                * policy.serving_safety_budget
            )
            applied[candidate.candidate_id] = round(max(-cap, min(cap, signal.raw_adjustment)), 8)

    learned_order: list[str] = []
    for group in groups:
        current = list(group)
        # Adjacent stable swaps make the displacement bound explicit and avoid
        # jumping across deterministic non-near-tie barriers.
        for _ in range(len(current)):
            changed = False
            for index in range(len(current) - 1):
                left, right = current[index], current[index + 1]
                left_score = left.deterministic_score + applied[left.candidate_id]
                right_score = right.deterministic_score + applied[right.candidate_id]
                left_new_rank = sum(len(prior) for prior in groups[:groups.index(group)]) + index + 2
                right_new_rank = left_new_rank - 1
                if (
                    right_score < left_score
                    and abs(left_new_rank - left.baseline_rank) <= policy.maximum_rank_displacement
                    and abs(right_new_rank - right.baseline_rank) <= policy.maximum_rank_displacement
                ):
                    current[index], current[index + 1] = right, left
                    changed = True
            if not changed:
                break
        learned_order.extend(item.candidate_id for item in current)

    rank_by_id = {candidate_id: index for index, candidate_id in enumerate(learned_order, start=1)}
    base_by_id = base.annotations_by_id
    annotations = tuple(CandidateAnnotation(
        candidate_id=candidate.candidate_id,
        baseline_rank=candidate.baseline_rank,
        deterministic_score=candidate.deterministic_score,
        raw_adjustment=base_by_id[candidate.candidate_id].raw_adjustment,
        applied_adjustment=applied[candidate.candidate_id],
        personalized_score=round(candidate.deterministic_score + applied[candidate.candidate_id], 8),
        personalized_rank=rank_by_id[candidate.candidate_id],
        model_version=base_by_id[candidate.candidate_id].model_version,
        maturity=base_by_id[candidate.candidate_id].maturity,
        calibration_factor=base_by_id[candidate.candidate_id].calibration_factor,
        evidence_categories=base_by_id[candidate.candidate_id].evidence_categories,
        estimate_p50_minutes=base_by_id[candidate.candidate_id].estimate_p50_minutes,
        estimate_p90_minutes=base_by_id[candidate.candidate_id].estimate_p90_minutes,
        completion_probability=base_by_id[candidate.candidate_id].completion_probability,
    ) for candidate in ordered_candidates)
    any_influence = any(value != 0 for value in applied.values())
    return AdaptiveRankingResult(
        schema_version=ADAPTIVE_RANKING_SCHEMA_VERSION,
        safe_candidates=safe,
        annotations=annotations,
        baseline_order=base.baseline_order,
        display_order=tuple(learned_order) if display_personalized else base.baseline_order,
        hard_fields_unchanged=True,
        fallback_reason=None if any_influence else "ranking_gates_not_met",
    )
