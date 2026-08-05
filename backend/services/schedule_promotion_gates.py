"""Lexicographic, fail-closed promotion gates for scheduling models."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from services.schedule_model_registry import RegistryCompatibility, promote_model


PROMOTION_GATE_VERSION = "scheduling-promotion-gates.v1"


@dataclass(frozen=True)
class PromotionPolicy:
    minimum_effort_p90_coverage: float = 0.80
    maximum_risk_ece: float = 0.10
    maximum_brier_degradation: float = 0.0
    maximum_deadline_miss_rate_degradation: float = 0.0
    minimum_deadline_risk_recall: float = 0.80
    maximum_overload_exposure_degradation: float = 0.0
    maximum_movement_rate: float = 0.25
    maximum_rejection_rate: float = 0.50
    maximum_undo_rate: float = 0.20
    maximum_false_intervention_rate: float = 0.20
    maximum_disparity_gap: float = 0.15
    maximum_p95_latency_ms: int = 75
    maximum_fallback_rate: float = 0.05


@dataclass(frozen=True)
class PromotionDecision:
    gate_version: str
    approved: bool
    blockers: tuple[str, ...]
    passed_layers: tuple[str, ...]
    ignored_metrics: tuple[str, ...]


def _number(metrics: Mapping[str, Any], key: str) -> Optional[float]:
    value = metrics.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def evaluate_promotion_gates(
    *,
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    policy: PromotionPolicy = PromotionPolicy(),
) -> PromotionDecision:
    """Evaluate every non-tradable layer in strict priority order."""
    blockers: list[str] = []
    passed: list[str] = []

    invariant_keys = (
        "hard_constraint_violations",
        "learned_auto_apply",
        "candidate_set_changes",
        "effort_conservation_changes",
        "cross_user_leakage_count",
        "ineligible_evidence_served_count",
    )
    missing_invariants = [key for key in invariant_keys if _number(candidate, key) is None]
    failed_invariants = [key for key in invariant_keys if (_number(candidate, key) or 0) != 0]
    if missing_invariants:
        blockers.extend(f"missing_safety_metric:{key}" for key in missing_invariants)
    if failed_invariants:
        blockers.extend(f"safety_violation:{key}" for key in failed_invariants)
    if not missing_invariants and not failed_invariants:
        passed.append("hard_constraint_safety")

    candidate_miss = _number(candidate, "deadline_miss_rate")
    baseline_miss = _number(baseline, "deadline_miss_rate")
    deadline_recall = _number(candidate, "deadline_risk_recall")
    if candidate_miss is None or baseline_miss is None or deadline_recall is None:
        blockers.append("missing_deadline_reliability_metric")
    elif candidate_miss > baseline_miss + policy.maximum_deadline_miss_rate_degradation:
        blockers.append("deadline_reliability_degraded")
    elif deadline_recall < policy.minimum_deadline_risk_recall:
        blockers.append("deadline_risk_recall_below_gate")
    else:
        passed.append("deadline_reliability")

    effort_coverage = _number(candidate, "effort_p90_coverage")
    candidate_ece = _number(candidate, "risk_ece")
    candidate_brier = _number(candidate, "brier_score")
    baseline_brier = _number(baseline, "brier_score")
    if None in (effort_coverage, candidate_ece, candidate_brier, baseline_brier):
        blockers.append("missing_calibration_metric")
    elif effort_coverage < policy.minimum_effort_p90_coverage:
        blockers.append("effort_interval_coverage_below_gate")
    elif candidate_ece > policy.maximum_risk_ece:
        blockers.append("risk_calibration_below_gate")
    elif candidate_brier > baseline_brier + policy.maximum_brier_degradation:
        blockers.append("brier_score_degraded")
    else:
        passed.append("calibrated_prediction")

    overload = _number(candidate, "overload_exposure_rate")
    baseline_overload = _number(baseline, "overload_exposure_rate")
    movement = _number(candidate, "movement_rate")
    if None in (overload, baseline_overload, movement):
        blockers.append("missing_stability_metric")
    elif overload > baseline_overload + policy.maximum_overload_exposure_degradation:
        blockers.append("overload_exposure_degraded")
    elif movement > policy.maximum_movement_rate:
        blockers.append("movement_burden_above_gate")
    else:
        passed.append("overload_and_stability")

    autonomy = {
        "rejection_rate": policy.maximum_rejection_rate,
        "undo_rate": policy.maximum_undo_rate,
        "false_intervention_rate": policy.maximum_false_intervention_rate,
    }
    autonomy_values = {key: _number(candidate, key) for key in autonomy}
    if any(value is None for value in autonomy_values.values()):
        blockers.append("missing_autonomy_metric")
    else:
        failed = [key for key, maximum in autonomy.items() if autonomy_values[key] > maximum]
        if failed:
            blockers.extend(f"autonomy_burden:{key}" for key in failed)
        else:
            passed.append("user_autonomy")

    deletion = _number(candidate, "deletion_correctness_rate")
    pending_deleted = _number(candidate, "deleted_evidence_served_count")
    if deletion is None or pending_deleted is None:
        blockers.append("missing_deletion_metric")
    elif deletion < 1 or pending_deleted != 0:
        blockers.append("deletion_correctness_failed")
    else:
        passed.append("privacy_and_deletion")

    disparity = _number(candidate, "maximum_slice_disparity_gap")
    slices_present = candidate.get("required_slices_present")
    if disparity is None or not isinstance(slices_present, bool):
        blockers.append("missing_disparity_or_slice_metric")
    elif not slices_present:
        blockers.append("required_slices_missing")
    elif disparity > policy.maximum_disparity_gap:
        blockers.append("slice_disparity_above_gate")
    else:
        passed.append("disparity_guardrail")

    latency = _number(candidate, "p95_latency_ms")
    fallback = _number(candidate, "fallback_rate")
    if latency is None or fallback is None:
        blockers.append("missing_operational_metric")
    elif latency > policy.maximum_p95_latency_ms:
        blockers.append("latency_above_gate")
    elif fallback > policy.maximum_fallback_rate:
        blockers.append("fallback_rate_above_gate")
    else:
        passed.append("operational_readiness")

    ignored = tuple(
        key for key in ("raw_completion_rate", "acceptance_rate", "engagement_rate", "task_count")
        if key in candidate
    )
    return PromotionDecision(
        gate_version=PROMOTION_GATE_VERSION,
        approved=not blockers,
        blockers=tuple(blockers),
        passed_layers=tuple(passed),
        ignored_metrics=ignored,
    )


def promote_after_gates(
    db: Session,
    model_id: str,
    *,
    candidate_metrics: Mapping[str, Any],
    baseline_metrics: Mapping[str, Any],
    approved_by: str,
    compatibility: RegistryCompatibility,
    policy: PromotionPolicy = PromotionPolicy(),
) -> tuple[PromotionDecision, Optional[Any]]:
    decision = evaluate_promotion_gates(
        candidate=candidate_metrics,
        baseline=baseline_metrics,
        policy=policy,
    )
    if not decision.approved:
        return decision, None
    row = promote_model(
        db,
        model_id,
        approved_by=approved_by,
        compatibility=compatibility,
    )
    row.lifecycle_reason = f"{PROMOTION_GATE_VERSION}:all_layers_passed"
    db.flush()
    return decision, row
