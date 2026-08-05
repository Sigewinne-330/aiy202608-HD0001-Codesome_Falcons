"""Staleness, sustained drift, recovery, and temporary-context policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
from typing import Optional, Sequence


DRIFT_POLICY_VERSION = "scheduling-drift.v1"


@dataclass(frozen=True)
class ResidualObservation:
    observed_date: date
    log_residual: float
    weight: float = 1.0

    def validate(self) -> None:
        if not math.isfinite(self.log_residual) or not -5 <= self.log_residual <= 5:
            raise ValueError("residual is outside its bounded range")
        if not math.isfinite(self.weight) or not 0 < self.weight <= 1:
            raise ValueError("residual weight must be in (0, 1]")


@dataclass(frozen=True)
class DriftAssessment:
    state: str
    reason: str
    recent_effective_n: float
    baseline_effective_n: float
    recent_mean_residual: Optional[float]
    baseline_mean_residual: Optional[float]
    residual_shift: Optional[float]
    policy_version: str = DRIFT_POLICY_VERSION


@dataclass(frozen=True)
class TemporaryContext:
    valid_from: date
    valid_until: date
    effort_multiplier: float
    source: str = "explicit_user_declaration"

    def validate(self) -> None:
        if self.valid_until < self.valid_from:
            raise ValueError("temporary context window is invalid")
        if not 0.75 <= self.effort_multiplier <= 1.25:
            raise ValueError("temporary context multiplier is outside its bounded range")
        if self.source != "explicit_user_declaration":
            raise ValueError("temporary context requires explicit user authority")


@dataclass(frozen=True)
class AdaptiveInfluence:
    personal_multiplier: float
    staleness_multiplier: float
    drift_multiplier: float
    context_effort_multiplier: float
    context_active: bool
    policy_version: str = DRIFT_POLICY_VERSION


def _weighted_mean(values: Sequence[ResidualObservation]) -> tuple[Optional[float], float]:
    total = sum(item.weight for item in values)
    if total <= 0:
        return None, 0.0
    return sum(item.log_residual * item.weight for item in values) / total, total


def detect_sustained_drift(
    observations: Sequence[ResidualObservation],
    *,
    reference_date: date,
    prior_state: str = "stable",
    recent_window_days: int = 30,
    baseline_window_days: int = 180,
    minimum_recent_effective_n: float = 5.0,
    minimum_baseline_effective_n: float = 5.0,
    watch_threshold: float = 0.20,
    drift_threshold: float = 0.35,
    recovery_threshold: float = 0.15,
) -> DriftAssessment:
    if prior_state not in {"stable", "watch", "drifted", "recovering"}:
        raise ValueError("invalid prior drift state")
    if not 7 <= recent_window_days < baseline_window_days <= 3_650:
        raise ValueError("drift windows are invalid")
    if not 0 < recovery_threshold <= watch_threshold < drift_threshold <= 2:
        raise ValueError("drift thresholds are invalid")
    for item in observations:
        item.validate()
    recent_start = reference_date - timedelta(days=recent_window_days - 1)
    baseline_start = reference_date - timedelta(days=baseline_window_days - 1)
    recent = [item for item in observations if recent_start <= item.observed_date <= reference_date]
    baseline = [item for item in observations if baseline_start <= item.observed_date < recent_start]
    recent_mean, recent_n = _weighted_mean(recent)
    baseline_mean, baseline_n = _weighted_mean(baseline)
    if recent_n < minimum_recent_effective_n or baseline_n < minimum_baseline_effective_n:
        return DriftAssessment(
            "stable" if prior_state == "stable" else prior_state,
            "insufficient_sustained_evidence",
            round(recent_n, 6),
            round(baseline_n, 6),
            round(recent_mean, 8) if recent_mean is not None else None,
            round(baseline_mean, 8) if baseline_mean is not None else None,
            None,
        )
    shift = recent_mean - baseline_mean
    absolute_shift = abs(shift)
    if prior_state == "drifted" and absolute_shift <= recovery_threshold:
        state, reason = "recovering", "recent_residuals_returning_to_baseline"
    elif absolute_shift >= drift_threshold:
        state, reason = "drifted", "sustained_residual_shift"
    elif absolute_shift >= watch_threshold:
        state, reason = "watch", "emerging_residual_shift"
    elif prior_state == "recovering":
        state, reason = "stable", "recovery_confirmed"
    else:
        state, reason = "stable", "residuals_within_stable_band"
    return DriftAssessment(
        state,
        reason,
        round(recent_n, 6),
        round(baseline_n, 6),
        round(recent_mean, 8),
        round(baseline_mean, 8),
        round(shift, 8),
    )


def compute_adaptive_influence(
    *,
    reference_date: date,
    latest_evidence_date: Optional[date],
    drift_state: str,
    temporary_context: Optional[TemporaryContext] = None,
    staleness_grace_days: int = 30,
    staleness_half_life_days: float = 90,
    hard_stale_days: int = 365,
) -> AdaptiveInfluence:
    if drift_state not in {"stable", "watch", "drifted", "recovering"}:
        raise ValueError("invalid drift state")
    if not 0 <= staleness_grace_days < hard_stale_days or staleness_half_life_days <= 0:
        raise ValueError("staleness policy is invalid")
    if latest_evidence_date is None:
        staleness = 0.0
    else:
        age = max(0, (reference_date - latest_evidence_date).days)
        if age >= hard_stale_days:
            staleness = 0.0
        else:
            staleness = 0.5 ** (max(0, age - staleness_grace_days) / staleness_half_life_days)
    drift = {"stable": 1.0, "watch": 0.75, "drifted": 0.35, "recovering": 0.60}[drift_state]
    context_multiplier = 1.0
    context_active = False
    if temporary_context is not None:
        temporary_context.validate()
        context_active = temporary_context.valid_from <= reference_date <= temporary_context.valid_until
        if context_active:
            context_multiplier = temporary_context.effort_multiplier
    return AdaptiveInfluence(
        personal_multiplier=round(staleness * drift, 8),
        staleness_multiplier=round(staleness, 8),
        drift_multiplier=drift,
        context_effort_multiplier=context_multiplier,
        context_active=context_active,
    )

