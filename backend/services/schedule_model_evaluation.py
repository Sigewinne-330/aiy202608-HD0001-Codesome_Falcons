"""Future-only, leakage-checked evaluation for adaptive scheduling models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math
from statistics import median
from typing import Any, Iterable, Optional


EVALUATION_SCHEMA_VERSION = "scheduling-model-evaluation.v1"


class TemporalEvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class EffortEvaluationPoint:
    decision_at: datetime
    feature_as_of: datetime
    outcome_at: datetime
    predicted_p50_minutes: float
    predicted_p90_minutes: float
    actual_minutes: float
    subject: str
    task_archetype: str


@dataclass(frozen=True)
class RiskEvaluationPoint:
    decision_at: datetime
    feature_as_of: datetime
    outcome_at: datetime
    completion_probability: float
    completed_before_deadline: bool
    subject: str
    task_archetype: str
    deadline_critical: bool = False


@dataclass(frozen=True)
class RankingEvaluationPoint:
    decision_at: datetime
    baseline_rank: int
    learned_rank: int
    hard_constraint_violation: bool = False
    learned_auto_applied: bool = False
    candidate_set_changed: bool = False
    effort_conservation_changed: bool = False


@dataclass(frozen=True)
class OperationalEvaluationPoint:
    decision_at: datetime
    latency_ms: int
    fallback: bool
    timed_out: bool = False


@dataclass(frozen=True)
class TemporalEvaluationReport:
    schema_version: str
    training_end: datetime
    evaluation_end: datetime
    effort_metrics: dict[str, Any]
    risk_metrics: dict[str, Any]
    ranking_metrics: dict[str, Any]
    operational_metrics: dict[str, Any]
    slice_metrics: dict[str, Any]
    required_slices_present: bool
    leakage_checks_passed: bool

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["training_end"] = self.training_end.isoformat()
        value["evaluation_end"] = self.evaluation_end.isoformat()
        return value


def _finite(value: float, field: str, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise TemporalEvaluationError(f"{field} must be finite")
    if minimum is not None and parsed < minimum:
        raise TemporalEvaluationError(f"{field} is below its lower bound")
    if maximum is not None and parsed > maximum:
        raise TemporalEvaluationError(f"{field} exceeds its upper bound")
    return parsed


def _validate_temporal(decision_at: datetime, feature_as_of: datetime, outcome_at: datetime, training_end: datetime, evaluation_end: datetime) -> None:
    if not training_end < decision_at <= evaluation_end:
        raise TemporalEvaluationError("evaluation decisions must be strictly future-only")
    if feature_as_of > decision_at:
        raise TemporalEvaluationError("feature snapshot leaks information after the decision")
    if outcome_at <= decision_at:
        raise TemporalEvaluationError("outcome must occur after the decision")


def _effort_metrics(points: list[EffortEvaluationPoint]) -> dict[str, Any]:
    if not points:
        return {"n": 0, "median_absolute_log_error": None, "p50_coverage": None, "p90_coverage": None, "underestimation_tail_rate": None}
    errors = [abs(math.log(item.predicted_p50_minutes) - math.log(item.actual_minutes)) for item in points]
    return {
        "n": len(points),
        "median_absolute_log_error": round(median(errors), 8),
        "mean_absolute_minutes": round(sum(abs(item.predicted_p50_minutes - item.actual_minutes) for item in points) / len(points), 8),
        "p50_coverage": round(sum(item.actual_minutes <= item.predicted_p50_minutes for item in points) / len(points), 8),
        "p90_coverage": round(sum(item.actual_minutes <= item.predicted_p90_minutes for item in points) / len(points), 8),
        "underestimation_tail_rate": round(sum(item.actual_minutes > item.predicted_p90_minutes for item in points) / len(points), 8),
    }


def _risk_metrics(points: list[RiskEvaluationPoint]) -> dict[str, Any]:
    if not points:
        return {"n": 0, "brier_score": None, "expected_calibration_error": None, "deadline_risk_recall": None, "calibration_bins": []}
    outcomes = [1.0 if item.completed_before_deadline else 0.0 for item in points]
    brier = sum((item.completion_probability - outcome) ** 2 for item, outcome in zip(points, outcomes)) / len(points)
    bins = []
    weighted_gap = 0.0
    for lower_index in range(5):
        lower = lower_index / 5
        upper = (lower_index + 1) / 5
        members = [
            (item.completion_probability, outcome)
            for item, outcome in zip(points, outcomes)
            if lower <= item.completion_probability < upper or (upper == 1 and item.completion_probability == 1)
        ]
        if not members:
            continue
        predicted = sum(item[0] for item in members) / len(members)
        observed = sum(item[1] for item in members) / len(members)
        gap = abs(predicted - observed)
        weighted_gap += gap * len(members) / len(points)
        bins.append({
            "lower": lower,
            "upper": upper,
            "n": len(members),
            "mean_prediction": round(predicted, 8),
            "observed_rate": round(observed, 8),
        })
    actual_misses = [item for item in points if item.deadline_critical and not item.completed_before_deadline]
    detected = [item for item in actual_misses if 1 - item.completion_probability >= 0.5]
    return {
        "n": len(points),
        "brier_score": round(brier, 8),
        "expected_calibration_error": round(weighted_gap, 8),
        "deadline_risk_recall": round(len(detected) / len(actual_misses), 8) if actual_misses else None,
        "calibration_bins": bins,
    }


def _slice_metrics(effort: list[EffortEvaluationPoint], risk: list[RiskEvaluationPoint], minimum_slice_n: int) -> dict[str, Any]:
    slices: dict[str, Any] = {}
    for dimension in ("subject", "task_archetype"):
        values = sorted({getattr(item, dimension) for item in [*effort, *risk] if getattr(item, dimension)})
        for value in values:
            effort_members = [item for item in effort if getattr(item, dimension) == value]
            risk_members = [item for item in risk if getattr(item, dimension) == value]
            total = len(effort_members) + len(risk_members)
            key = f"{dimension}:{value}"
            slices[key] = {
                "n": total,
                "sufficient": total >= minimum_slice_n,
                "effort": _effort_metrics(effort_members),
                "risk": _risk_metrics(risk_members),
            }
    return slices


def evaluate_temporal_models(
    *,
    training_end: datetime,
    evaluation_end: datetime,
    effort_points: Iterable[EffortEvaluationPoint] = (),
    risk_points: Iterable[RiskEvaluationPoint] = (),
    ranking_points: Iterable[RankingEvaluationPoint] = (),
    operational_points: Iterable[OperationalEvaluationPoint] = (),
    required_slices: Iterable[str] = (),
    minimum_slice_n: int = 5,
) -> TemporalEvaluationReport:
    if evaluation_end <= training_end:
        raise TemporalEvaluationError("evaluation window must follow training")
    if not 1 <= minimum_slice_n <= 10_000:
        raise TemporalEvaluationError("minimum slice size is invalid")
    effort = list(effort_points)
    risk = list(risk_points)
    ranking = list(ranking_points)
    operations = list(operational_points)
    for item in effort:
        _validate_temporal(item.decision_at, item.feature_as_of, item.outcome_at, training_end, evaluation_end)
        _finite(item.predicted_p50_minutes, "predicted_p50_minutes", minimum=1)
        _finite(item.predicted_p90_minutes, "predicted_p90_minutes", minimum=item.predicted_p50_minutes)
        _finite(item.actual_minutes, "actual_minutes", minimum=1)
    for item in risk:
        _validate_temporal(item.decision_at, item.feature_as_of, item.outcome_at, training_end, evaluation_end)
        _finite(item.completion_probability, "completion_probability", minimum=0, maximum=1)
    for item in [*ranking, *operations]:
        if not training_end < item.decision_at <= evaluation_end:
            raise TemporalEvaluationError("all evaluation records must be future-only")
    for item in operations:
        if item.latency_ms < 0:
            raise TemporalEvaluationError("latency cannot be negative")

    invariant_failures = {
        "hard_constraint_violations": sum(item.hard_constraint_violation for item in ranking),
        "learned_auto_apply": sum(item.learned_auto_applied for item in ranking),
        "candidate_set_changes": sum(item.candidate_set_changed for item in ranking),
        "effort_conservation_changes": sum(item.effort_conservation_changed for item in ranking),
    }
    latencies = sorted(item.latency_ms for item in operations)
    p95_index = max(0, math.ceil(0.95 * len(latencies)) - 1) if latencies else 0
    slices = _slice_metrics(effort, risk, minimum_slice_n)
    required = tuple(required_slices)
    required_present = bool(required) and all(
        key in slices and slices[key]["sufficient"] for key in required
    )
    return TemporalEvaluationReport(
        schema_version=EVALUATION_SCHEMA_VERSION,
        training_end=training_end,
        evaluation_end=evaluation_end,
        effort_metrics=_effort_metrics(effort),
        risk_metrics=_risk_metrics(risk),
        ranking_metrics={
            "n": len(ranking),
            **invariant_failures,
            "deterministic_invariants_passed": not any(invariant_failures.values()),
            "maximum_observed_displacement": max(
                (abs(item.learned_rank - item.baseline_rank) for item in ranking), default=0
            ),
        },
        operational_metrics={
            "n": len(operations),
            "p95_latency_ms": latencies[p95_index] if latencies else None,
            "fallback_rate": round(sum(item.fallback for item in operations) / len(operations), 8) if operations else None,
            "timeout_rate": round(sum(item.timed_out for item in operations) / len(operations), 8) if operations else None,
        },
        slice_metrics=slices,
        required_slices_present=required_present,
        leakage_checks_passed=True,
    )
