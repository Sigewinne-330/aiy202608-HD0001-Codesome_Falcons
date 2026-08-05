"""Separately consented display-only randomization for safe near ties."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Optional

from services.schedule_adaptive_ranking import AdaptiveRankingResult, SafeCandidateSnapshot


EXPLORATION_SCHEMA_VERSION = "scheduling-near-tie-exploration.v1"


@dataclass(frozen=True)
class ExplorationAssignment:
    schema_version: str
    baseline_order: tuple[str, ...]
    display_order: tuple[str, ...]
    eligible_candidate_ids: tuple[str, ...]
    randomized: bool
    assignment_probability: Optional[float]
    assignment_denominator: Optional[int]
    exclusion_reason: Optional[str]


def assign_near_tie_display(
    candidates: tuple[SafeCandidateSnapshot, ...],
    ranking: AdaptiveRankingResult,
    *,
    enabled: bool,
    consent_enabled: bool,
    near_tie_score_delta: float,
    minimum_maturity: float = 0.5,
    minimum_calibration_factor: float = 0.6,
    random_source: Optional[random.Random] = None,
) -> ExplorationAssignment:
    baseline = ranking.baseline_order
    reason = None
    if not enabled:
        reason = "runtime_disabled"
    elif not consent_enabled:
        reason = "consent_disabled"
    elif len(candidates) < 2:
        reason = "unique_candidate"
    if reason:
        return ExplorationAssignment(
            EXPLORATION_SCHEMA_VERSION, baseline, baseline, (), False, None, None, reason
        )

    by_annotation = ranking.annotations_by_id
    ordered = sorted(candidates, key=lambda item: item.baseline_rank)
    eligible = []
    for candidate in ordered:
        annotation = by_annotation[candidate.candidate_id]
        if candidate.deadline_critical:
            break
        if annotation.maturity < minimum_maturity or annotation.calibration_factor < minimum_calibration_factor:
            break
        if eligible and abs(candidate.deterministic_score - eligible[-1].deterministic_score) > near_tie_score_delta:
            break
        eligible.append(candidate)
    if len(eligible) < 2:
        return ExplorationAssignment(
            EXPLORATION_SCHEMA_VERSION,
            baseline,
            baseline,
            tuple(item.candidate_id for item in eligible),
            False,
            None,
            None,
            "no_eligible_noncritical_near_tie",
        )

    eligible_ids = [item.candidate_id for item in eligible]
    source = random_source or random.SystemRandom()
    source.shuffle(eligible_ids)
    eligible_set = set(eligible_ids)
    tail = [candidate_id for candidate_id in baseline if candidate_id not in eligible_set]
    denominator = math.factorial(len(eligible_ids))
    probability = 1.0 / denominator
    return ExplorationAssignment(
        schema_version=EXPLORATION_SCHEMA_VERSION,
        baseline_order=baseline,
        display_order=tuple(eligible_ids + tail),
        eligible_candidate_ids=tuple(item.candidate_id for item in eligible),
        randomized=True,
        assignment_probability=probability,
        assignment_denominator=denominator,
        exclusion_reason=None,
    )
