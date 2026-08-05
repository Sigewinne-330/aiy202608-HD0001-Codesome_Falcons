"""Interpretable empirical-Bayes effort prediction in log active minutes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from typing import Any, Optional

from sqlalchemy.orm import Session

from services.schedule_drift import compute_adaptive_influence
from services.schedule_features import FeatureHierarchy, HierarchyLevel, resolve_feature_hierarchy


EFFORT_MODEL_ALGORITHM_VERSION = "scheduling-effort-empirical-bayes.v1"
_NORMAL_QUANTILE_90 = 1.2815515655446004


@dataclass(frozen=True)
class EffortModelPolicy:
    correction_gate_effective_n: float = 5.0
    shrinkage_k: float = 5.0
    segment_maximum_weight: float = 0.80
    middle_maximum_weight: float = 0.60
    user_global_maximum_weight: float = 0.35
    stale_after_days: int = 180
    minimum_log_sigma: float = 0.15
    maximum_log_sigma: float = 1.50
    maximum_prior_log_shift: float = 2.50
    minimum_minutes: int = 5
    maximum_minutes: int = 10_080

    def validate(self) -> None:
        if not 1 <= self.correction_gate_effective_n <= 100:
            raise ValueError("correction gate must be between 1 and 100")
        if not 0.1 <= self.shrinkage_k <= 100:
            raise ValueError("shrinkage_k must be between 0.1 and 100")
        for value in (
            self.segment_maximum_weight,
            self.middle_maximum_weight,
            self.user_global_maximum_weight,
        ):
            if not 0 <= value <= 1:
                raise ValueError("personal influence caps must be probabilities")
        if not self.user_global_maximum_weight <= self.middle_maximum_weight <= self.segment_maximum_weight:
            raise ValueError("personal influence caps must increase with specificity")
        if not 30 <= self.stale_after_days <= 3_650:
            raise ValueError("stale threshold must be between 30 and 3650 days")
        if not 0 < self.minimum_log_sigma <= self.maximum_log_sigma <= 3:
            raise ValueError("log sigma bounds are invalid")
        if not 0 < self.minimum_minutes < self.maximum_minutes:
            raise ValueError("minute bounds are invalid")


@dataclass(frozen=True)
class EffortPrediction:
    p10_active_minutes: int
    p50_active_minutes: int
    p90_active_minutes: int
    mean_log_minutes: float
    log_sigma: float
    effective_sample_size: float
    correction_gate_effective_n: float
    correction_gate_passed: bool
    personal_weight: float
    selected_personal_level: Optional[str]
    maturity_state: str
    maturity_score: float
    freshness_state: str
    latest_evidence_date: Optional[date]
    days_since_evidence: Optional[int]
    calibration_state: str
    prior_level: str
    prior_version: str
    taxonomy_version: str
    feature_schema_version: str
    algorithm_version: str
    model_version: str
    source_hierarchy: tuple[str, ...]
    fallback_reason: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["latest_evidence_date"] = self.latest_evidence_date.isoformat() if self.latest_evidence_date else None
        value["source_hierarchy"] = list(self.source_hierarchy)
        return value


def _finite_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _latest_date(level: Optional[HierarchyLevel]) -> Optional[date]:
    if level is None:
        return None
    raw = level.statistics.get("latest_outcome_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def _freshness(reference_date: date, level: Optional[HierarchyLevel]) -> tuple[str, Optional[date], Optional[int]]:
    latest = _latest_date(level)
    if latest is None:
        return "no_evidence", None, None
    age = max(0, (reference_date - latest).days)
    if age <= 30:
        state = "fresh"
    elif age <= 90:
        state = "aging"
    else:
        state = "stale"
    return state, latest, age


def _maturity(effective_n: float, gate: float) -> tuple[str, float]:
    score = min(1.0, max(0.0, effective_n) / 20.0)
    if effective_n <= 0:
        state = "cold_start"
    elif effective_n < gate:
        state = "warming_up"
    elif effective_n < 20:
        state = "early_personal"
    elif effective_n < 50:
        state = "developing"
    else:
        state = "mature"
    return state, round(score, 6)


def _product_prior(hierarchy: FeatureHierarchy) -> HierarchyLevel:
    by_name = {item.level: item for item in hierarchy.specific_to_broad}
    return by_name.get("ib_prior") or by_name["global_prior"]


def _personal_candidates(hierarchy: FeatureHierarchy) -> list[HierarchyLevel]:
    values = [
        item for item in hierarchy.specific_to_broad
        if item.level in {"user_segment", "user_subject", "user_archetype", "user_global"}
    ]
    by_name = {item.level: item for item in values}
    ordered: list[HierarchyLevel] = []
    if by_name.get("user_segment"):
        ordered.append(by_name["user_segment"])
    middle = [item for item in values if item.level in {"user_subject", "user_archetype"}]
    if middle:
        ordered.append(max(middle, key=lambda item: (item.effective_sample_size, item.level)))
    if by_name.get("user_global"):
        ordered.append(by_name["user_global"])
    return ordered


def _maximum_weight(level: HierarchyLevel, policy: EffortModelPolicy) -> float:
    if level.level == "user_segment":
        return policy.segment_maximum_weight
    if level.level in {"user_subject", "user_archetype"}:
        return policy.middle_maximum_weight
    return policy.user_global_maximum_weight


def _bounded_minutes(value: float, policy: EffortModelPolicy) -> int:
    return int(max(policy.minimum_minutes, min(policy.maximum_minutes, round(value))))


def _model_version(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{EFFORT_MODEL_ALGORITHM_VERSION}:{hashlib.sha256(encoded).hexdigest()[:20]}"


def predict_effort_distribution(
    db: Session,
    user_id: int,
    *,
    subject: Optional[str],
    task_archetype: str,
    reference_date: date,
    policy: EffortModelPolicy = EffortModelPolicy(),
) -> EffortPrediction:
    policy.validate()
    hierarchy = resolve_feature_hierarchy(
        db,
        user_id,
        subject=subject,
        task_archetype=task_archetype,
        reference_date=reference_date,
    )
    prior = _product_prior(hierarchy)
    prior_mean = _finite_float(prior.statistics.get("mean_log_minutes"))
    prior_variance = _finite_float(prior.statistics.get("variance_log_minutes"))
    if prior_mean is None or prior_variance is None or prior_variance <= 0:
        raise ValueError("versioned effort prior is invalid")
    prior_sigma = min(policy.maximum_log_sigma, max(policy.minimum_log_sigma, math.sqrt(prior_variance)))
    prior_variance = prior_sigma * prior_sigma

    candidates = _personal_candidates(hierarchy)
    diagnostic = candidates[0] if candidates else None
    selected = None
    selected_freshness = ("no_evidence", None, None)
    fallback_reason = None
    for candidate in candidates:
        freshness = _freshness(reference_date, candidate)
        mean = _finite_float(candidate.statistics.get("mean_log_minutes"))
        variance = _finite_float(candidate.statistics.get("variance_log_minutes"))
        if candidate.effective_sample_size < policy.correction_gate_effective_n:
            continue
        if freshness[2] is not None and freshness[2] > policy.stale_after_days:
            fallback_reason = "personal_evidence_stale"
            continue
        if mean is None or variance is None or variance < 0:
            fallback_reason = "invalid_personal_statistics"
            continue
        selected = candidate
        selected_freshness = freshness
        break

    diagnostic_level = selected or diagnostic
    effective_n = diagnostic_level.effective_sample_size if diagnostic_level else 0.0
    freshness_state, latest_date, age_days = _freshness(reference_date, diagnostic_level)
    maturity_state, maturity_score = _maturity(effective_n, policy.correction_gate_effective_n)
    posterior_mean = prior_mean
    posterior_variance = prior_variance
    personal_weight = 0.0
    gate_passed = selected is not None
    if selected is not None:
        observed_mean = _finite_float(selected.statistics.get("mean_log_minutes"))
        observed_variance = _finite_float(selected.statistics.get("variance_log_minutes"))
        observed_mean = min(
            prior_mean + policy.maximum_prior_log_shift,
            max(prior_mean - policy.maximum_prior_log_shift, observed_mean),
        )
        observed_variance = min(
            policy.maximum_log_sigma ** 2,
            max(policy.minimum_log_sigma ** 2, observed_variance),
        )
        raw_weight = selected.effective_sample_size / (selected.effective_sample_size + policy.shrinkage_k)
        adaptive = compute_adaptive_influence(
            reference_date=reference_date,
            latest_evidence_date=latest_date,
            drift_state=str(selected.statistics.get("drift_state") or "stable"),
            hard_stale_days=policy.stale_after_days,
        )
        personal_weight = min(_maximum_weight(selected, policy), raw_weight) * adaptive.personal_multiplier
        posterior_mean = (1 - personal_weight) * prior_mean + personal_weight * observed_mean
        posterior_variance = (
            (1 - personal_weight) * prior_variance
            + personal_weight * observed_variance
            + personal_weight * (1 - personal_weight) * (observed_mean - prior_mean) ** 2
        )
        freshness_state, latest_date, age_days = selected_freshness
        effective_n = selected.effective_sample_size
        maturity_state, maturity_score = _maturity(effective_n, policy.correction_gate_effective_n)
    elif candidates and fallback_reason is None:
        fallback_reason = "correction_gate_not_met"
    elif not candidates:
        fallback_reason = "no_personal_evidence"

    sigma = min(policy.maximum_log_sigma, max(policy.minimum_log_sigma, math.sqrt(max(0.0, posterior_variance))))
    if selected is None:
        p10 = int(prior.statistics["p10_active_minutes"])
        p50 = int(prior.statistics["p50_active_minutes"])
        p90 = int(prior.statistics["p90_active_minutes"])
    else:
        p10 = _bounded_minutes(math.exp(posterior_mean - _NORMAL_QUANTILE_90 * sigma), policy)
        p50 = _bounded_minutes(math.exp(posterior_mean), policy)
        p90 = _bounded_minutes(math.exp(posterior_mean + _NORMAL_QUANTILE_90 * sigma), policy)
    p10 = min(p10, p50)
    p90 = max(p90, p50)
    version_payload = {
        "algorithm_version": EFFORT_MODEL_ALGORITHM_VERSION,
        "feature_schema_version": hierarchy.feature_schema_version,
        "reference_date": reference_date.isoformat(),
        "subject": subject,
        "task_archetype": task_archetype,
        "policy": asdict(policy),
        "prior": prior.statistics,
        "selected_level": selected.level if selected else None,
        "selected_statistics": selected.statistics if selected else None,
        "selected_effective_n": selected.effective_sample_size if selected else 0,
        "posterior_mean": round(posterior_mean, 10),
        "posterior_sigma": round(sigma, 10),
    }
    return EffortPrediction(
        p10_active_minutes=p10,
        p50_active_minutes=p50,
        p90_active_minutes=p90,
        mean_log_minutes=round(posterior_mean, 8),
        log_sigma=round(sigma, 8),
        effective_sample_size=round(effective_n, 6),
        correction_gate_effective_n=policy.correction_gate_effective_n,
        correction_gate_passed=gate_passed,
        personal_weight=round(personal_weight, 6),
        selected_personal_level=selected.level if selected else None,
        maturity_state=maturity_state,
        maturity_score=maturity_score,
        freshness_state=freshness_state,
        latest_evidence_date=latest_date,
        days_since_evidence=age_days,
        calibration_state="uncalibrated_personal" if selected else "prior_only",
        prior_level=prior.level,
        prior_version=str(prior.statistics["prior_version"]),
        taxonomy_version=str(prior.statistics["taxonomy_version"]),
        feature_schema_version=hierarchy.feature_schema_version,
        algorithm_version=EFFORT_MODEL_ALGORITHM_VERSION,
        model_version=_model_version(version_payload),
        source_hierarchy=tuple(item.level for item in hierarchy.specific_to_broad),
        fallback_reason=fallback_reason,
    )
