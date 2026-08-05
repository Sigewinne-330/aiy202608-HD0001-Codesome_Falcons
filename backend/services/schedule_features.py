"""Versioned, consent-aware sufficient statistics for personal effort.

The materialized rows are mergeable data, never executable model artifacts.
Each eligible label has bounded influence through evidence-quality, recency,
retention, and outlier policies before it can affect a personal estimate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingFeatureSnapshot, SchedulingOutcomeLabel
from models.task_new import Task
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_source_access import owned_schedule_source
from services.schedule_taxonomy import (
    EffortPrior,
    normalize_ib_subject,
    normalize_task_archetype,
    resolve_effort_prior,
)


SUFFICIENT_STATISTICS_VERSION = "scheduling-sufficient-statistics.v1"


@dataclass(frozen=True)
class FeatureDerivationPolicy:
    long_window_days: int = 365
    recent_window_days: int = 42
    recency_half_life_days: float = 120.0
    recent_half_life_days: float = 21.0
    minimum_active_minutes: float = 5.0
    maximum_active_minutes: float = 1_440.0
    maximum_prior_log_deviation: float = 2.5
    maximum_event_weight: float = 1.0

    def validate(self) -> None:
        if not 30 <= self.long_window_days <= 3_650:
            raise ValueError("long window must be between 30 and 3650 days")
        if not 7 <= self.recent_window_days <= self.long_window_days:
            raise ValueError("recent window must be between 7 days and the long window")
        if not 1 <= self.recency_half_life_days <= 3_650 or not 1 <= self.recent_half_life_days <= 365:
            raise ValueError("recency half-lives are outside bounded ranges")
        if not 0 < self.minimum_active_minutes < self.maximum_active_minutes <= 10_080:
            raise ValueError("active-minute caps are invalid")
        if not 0.5 <= self.maximum_prior_log_deviation <= 5 or not 0 < self.maximum_event_weight <= 1:
            raise ValueError("influence caps are invalid")


@dataclass(frozen=True)
class _FeatureObservation:
    label_id: int
    outcome_date: date
    active_minutes: float
    log_active_minutes: float
    quality_weight: float
    subject: Optional[str]
    archetype: str
    capped: bool


@dataclass(frozen=True)
class HierarchyLevel:
    level: str
    scope_type: str
    scope_key: str
    effective_sample_size: float
    statistics: dict[str, Any]
    provenance: str


@dataclass(frozen=True)
class FeatureHierarchy:
    selected: HierarchyLevel
    specific_to_broad: tuple[HierarchyLevel, ...]
    broad_to_specific: tuple[HierarchyLevel, ...]
    reference_date: date
    feature_schema_version: str = SUFFICIENT_STATISTICS_VERSION


_PROVENANCE_WEIGHTS = {
    "active_timer_measured": 1.00,
    "active_timer_low_confidence": 0.35,
    "user_reported_proxy": 0.60,
}
_CONFIDENCE_WEIGHTS = {"high": 1.00, "medium": 0.75, "low": 0.40, "unknown": 0.20}


def _source_classification(db: Session, user_id: int, label: SchedulingOutcomeLabel):
    source = owned_schedule_source(db, user_id, label.source_type, label.source_id)
    if source is None:
        return None
    if label.source_type == "subtask":
        parent = db.query(Task).filter(Task.id == source.task_id, Task.user_id == user_id).first()
        subject_value = getattr(parent, "subject", None) if parent else None
        structured_kind = getattr(source, "schedule_kind", None) or getattr(parent, "schedule_kind", None)
        title = getattr(source, "name", "")
        description = getattr(source, "description", "")
    else:
        subject_value = getattr(source, "subject", None)
        structured_kind = getattr(source, "schedule_kind", None)
        title = getattr(source, "title", "")
        description = getattr(source, "description", "")
    subject = normalize_ib_subject(subject_value)
    archetype = normalize_task_archetype(
        title=title,
        description=description,
        structured_kind=structured_kind,
    )
    return subject, archetype


def _quality_weight(label: SchedulingOutcomeLabel) -> float:
    provenance = _PROVENANCE_WEIGHTS.get(label.active_minutes_provenance or "", 0.0)
    confidence = _CONFIDENCE_WEIGHTS.get(label.label_confidence or "unknown", 0.20)
    interval = 1.0 if label.interval_complete else (0.75 if label.active_minutes_provenance == "user_reported_proxy" else 0.50)
    return provenance * confidence * interval


def _recency_weight(age_days: int, half_life_days: float) -> float:
    return 0.5 ** (max(0, age_days) / half_life_days)


def _prior_for(subject: Optional[str], archetype: str) -> EffortPrior:
    return resolve_effort_prior(task_archetype=archetype, subject=subject)


def _observation(
    db: Session,
    user_id: int,
    label: SchedulingOutcomeLabel,
    policy: FeatureDerivationPolicy,
) -> Optional[_FeatureObservation]:
    classification = _source_classification(db, user_id, label)
    if classification is None:
        return None
    subject_resolution, archetype_resolution = classification
    subject = subject_resolution.subject if subject_resolution.status == "recognized" else None
    archetype = archetype_resolution.task_archetype
    quality = min(policy.maximum_event_weight, _quality_weight(label))
    if quality <= 0:
        return None
    raw_minutes = float(label.active_minutes)
    bounded_minutes = min(policy.maximum_active_minutes, max(policy.minimum_active_minutes, raw_minutes))
    prior = _prior_for(subject, archetype)
    raw_log = math.log(bounded_minutes)
    lower = prior.log_mean - policy.maximum_prior_log_deviation
    upper = prior.log_mean + policy.maximum_prior_log_deviation
    bounded_log = min(upper, max(lower, raw_log))
    capped = not math.isclose(raw_minutes, bounded_minutes) or not math.isclose(raw_log, bounded_log)
    return _FeatureObservation(
        label_id=label.id,
        outcome_date=label.outcome_cutoff_at.date(),
        active_minutes=bounded_minutes,
        log_active_minutes=bounded_log,
        quality_weight=quality,
        subject=subject,
        archetype=archetype,
        capped=capped,
    )


def _source_hash(observations: list[_FeatureObservation]) -> str:
    payload = [
        [item.label_id, item.outcome_date.isoformat(), round(item.log_active_minutes, 8), round(item.quality_weight, 8)]
        for item in sorted(observations, key=lambda row: (row.outcome_date, row.label_id))
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


def _statistics(
    observations: list[_FeatureObservation],
    reference_date: date,
    *,
    half_life_days: float,
) -> dict[str, Any]:
    weighted = []
    for item in observations:
        age = max(0, (reference_date - item.outcome_date).days)
        recency = _recency_weight(age, half_life_days)
        weight = min(1.0, item.quality_weight * recency)
        weighted.append((item, weight, recency))
    sum_w = sum(weight for _, weight, _ in weighted)
    sum_w2 = sum(weight * weight for _, weight, _ in weighted)
    sum_wx = sum(weight * item.log_active_minutes for item, weight, _ in weighted)
    sum_wx2 = sum(weight * item.log_active_minutes * item.log_active_minutes for item, weight, _ in weighted)
    mean = sum_wx / sum_w if sum_w else None
    variance = max(0.0, sum_wx2 / sum_w - mean * mean) if sum_w and mean is not None else None
    return {
        "raw_count": len(observations),
        "effective_sample_size": round(sum_w, 8),
        "kish_effective_sample_size": round((sum_w * sum_w / sum_w2) if sum_w2 else 0.0, 8),
        "sum_weight": round(sum_w, 8),
        "sum_weight_squared": round(sum_w2, 8),
        "sum_weighted_log_minutes": round(sum_wx, 8),
        "sum_weighted_log_minutes_squared": round(sum_wx2, 8),
        "mean_log_minutes": round(mean, 8) if mean is not None else None,
        "variance_log_minutes": round(variance, 8) if variance is not None else None,
        "minimum_bounded_minutes": round(min((item.active_minutes for item in observations), default=0), 4),
        "maximum_bounded_minutes": round(max((item.active_minutes for item in observations), default=0), 4),
        "capped_count": sum(1 for item in observations if item.capped),
        "earliest_outcome_date": min((item.outcome_date for item in observations), default=None).isoformat() if observations else None,
        "latest_outcome_date": max((item.outcome_date for item in observations), default=None).isoformat() if observations else None,
        "source_label_hash": _source_hash(observations),
        "source_label_count": len(observations),
    }


def _scope_memberships(item: _FeatureObservation) -> tuple[tuple[str, str], ...]:
    scopes = [("user_global", "all")]
    if item.subject:
        scopes.append(("user_subject", item.subject))
    if item.archetype:
        scopes.append(("user_archetype", item.archetype))
    if item.subject and item.archetype not in {"unknown", "mixed"}:
        scopes.append(("user_segment", f"{item.subject}|{item.archetype}"))
    return tuple(scopes)


def derive_sufficient_statistics(
    db: Session,
    user_id: int,
    *,
    reference_date: date,
    policy: FeatureDerivationPolicy = FeatureDerivationPolicy(),
) -> tuple[SchedulingFeatureSnapshot, ...]:
    policy.validate()
    consent = get_or_create_private_consent(db, user_id)
    if not consent.operational_personalization_enabled:
        return ()
    effective_long_days = min(policy.long_window_days, int(consent.raw_event_retention_days))
    long_start = reference_date - timedelta(days=effective_long_days - 1)
    recent_start = max(long_start, reference_date - timedelta(days=policy.recent_window_days - 1))
    cutoff = datetime.combine(reference_date, time.max)
    labels = db.query(SchedulingOutcomeLabel).filter(
        SchedulingOutcomeLabel.user_id == user_id,
        SchedulingOutcomeLabel.outcome_cutoff_at <= cutoff,
    ).order_by(SchedulingOutcomeLabel.outcome_cutoff_at.asc(), SchedulingOutcomeLabel.id.asc()).all()

    excluded = {
        "not_personal_eligible": 0,
        "watermark_mismatch": 0,
        "invalidated": 0,
        "retention_or_window": 0,
        "missing_effort": 0,
        "missing_source_or_zero_quality": 0,
    }
    eligible: list[_FeatureObservation] = []
    for label in labels:
        outcome_date = label.outcome_cutoff_at.date()
        if not label.eligible_personal:
            excluded["not_personal_eligible"] += 1
            continue
        if label.eligibility_watermark != consent.eligibility_watermark:
            excluded["watermark_mismatch"] += 1
            continue
        if label.invalidated_at is not None:
            excluded["invalidated"] += 1
            continue
        if outcome_date < long_start:
            excluded["retention_or_window"] += 1
            continue
        if label.active_minutes is None or float(label.active_minutes) <= 0:
            excluded["missing_effort"] += 1
            continue
        observation = _observation(db, user_id, label, policy)
        if observation is None:
            excluded["missing_source_or_zero_quality"] += 1
            continue
        eligible.append(observation)

    grouped: dict[tuple[str, str], list[_FeatureObservation]] = {}
    for item in eligible:
        for scope in _scope_memberships(item):
            grouped.setdefault(scope, []).append(item)

    rows: list[SchedulingFeatureSnapshot] = []
    policy_json = {**asdict(policy), "effective_long_window_days": effective_long_days}
    for (scope_type, scope_key), observations in sorted(grouped.items()):
        recent = [item for item in observations if item.outcome_date >= recent_start]
        long_statistics = _statistics(
            observations,
            reference_date,
            half_life_days=policy.recency_half_life_days,
        )
        long_statistics["excluded_counts"] = dict(excluded)
        long_statistics["classification_provenance"] = "current_owner_scoped_source"
        recent_statistics = _statistics(
            recent,
            reference_date,
            half_life_days=policy.recent_half_life_days,
        )
        existing = db.query(SchedulingFeatureSnapshot).filter_by(
            user_id=user_id,
            scope_type=scope_type,
            scope_key=scope_key,
            reference_date=reference_date,
            feature_schema_version=SUFFICIENT_STATISTICS_VERSION,
        ).one_or_none()
        values = {
            "window_start": long_start,
            "window_end": reference_date,
            "source_eligibility_watermark": consent.eligibility_watermark,
            "effective_sample_size": long_statistics["effective_sample_size"],
            "sufficient_statistics": long_statistics,
            "recent_statistics": recent_statistics,
            "recency_policy": policy_json,
            "drift_state": "stable",
            "eligible_cross_user": bool(consent.cross_user_learning_enabled),
            "invalidated_at": None,
        }
        if existing is None:
            existing = SchedulingFeatureSnapshot(
                user_id=user_id,
                scope_type=scope_type,
                scope_key=scope_key,
                reference_date=reference_date,
                feature_schema_version=SUFFICIENT_STATISTICS_VERSION,
                **values,
            )
            db.add(existing)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        rows.append(existing)
    db.flush()
    return tuple(rows)


def _snapshot_level(row: SchedulingFeatureSnapshot, level: str) -> HierarchyLevel:
    statistics = dict(row.sufficient_statistics or {})
    statistics["drift_state"] = row.drift_state
    return HierarchyLevel(
        level=level,
        scope_type=row.scope_type,
        scope_key=row.scope_key,
        effective_sample_size=float(row.effective_sample_size),
        statistics=statistics,
        provenance="eligible_personal_sufficient_statistics",
    )


def _prior_level(prior: EffortPrior, level: str) -> HierarchyLevel:
    return HierarchyLevel(
        level=level,
        scope_type=prior.scope,
        scope_key=f"{prior.subject or '*'}|{prior.task_archetype}",
        effective_sample_size=0.0,
        statistics={
            "mean_log_minutes": prior.log_mean,
            "variance_log_minutes": round(prior.log_sigma * prior.log_sigma, 8),
            "p10_active_minutes": prior.p10_active_minutes,
            "p50_active_minutes": prior.p50_active_minutes,
            "p90_active_minutes": prior.p90_active_minutes,
            "prior_version": prior.prior_version,
            "taxonomy_version": prior.taxonomy_version,
            "cold_start": True,
        },
        provenance=prior.provenance,
    )


def resolve_feature_hierarchy(
    db: Session,
    user_id: int,
    *,
    subject: Optional[str],
    task_archetype: str,
    reference_date: date,
) -> FeatureHierarchy:
    consent = get_or_create_private_consent(db, user_id)
    subject_resolution = normalize_ib_subject(subject)
    canonical_subject = subject_resolution.subject if subject_resolution.status == "recognized" else None
    archetype_resolution = normalize_task_archetype(structured_kind=task_archetype)
    canonical_archetype = archetype_resolution.task_archetype

    requested = [
        ("user_segment", f"{canonical_subject}|{canonical_archetype}", "user_segment") if canonical_subject and canonical_archetype not in {"unknown", "mixed"} else None,
        ("user_subject", canonical_subject, "user_subject") if canonical_subject else None,
        ("user_archetype", canonical_archetype, "user_archetype"),
        ("user_global", "all", "user_global"),
    ]
    personal_levels: list[HierarchyLevel] = []
    if consent.operational_personalization_enabled:
        for value in requested:
            if value is None:
                continue
            scope_type, scope_key, level = value
            row = db.query(SchedulingFeatureSnapshot).filter(
                SchedulingFeatureSnapshot.user_id == user_id,
                SchedulingFeatureSnapshot.scope_type == scope_type,
                SchedulingFeatureSnapshot.scope_key == scope_key,
                SchedulingFeatureSnapshot.reference_date <= reference_date,
                SchedulingFeatureSnapshot.feature_schema_version == SUFFICIENT_STATISTICS_VERSION,
                SchedulingFeatureSnapshot.source_eligibility_watermark == consent.eligibility_watermark,
                SchedulingFeatureSnapshot.invalidated_at.is_(None),
            ).order_by(
                SchedulingFeatureSnapshot.reference_date.desc(),
                SchedulingFeatureSnapshot.id.desc(),
            ).first()
            if row is not None and float(row.effective_sample_size) > 0:
                personal_levels.append(_snapshot_level(row, level))

    general_prior = resolve_effort_prior(task_archetype=canonical_archetype, subject=None)
    broad = [_prior_level(general_prior, "global_prior")]
    ib_prior = resolve_effort_prior(task_archetype=canonical_archetype, subject=canonical_subject)
    if ib_prior.scope == "ib_subject_archetype":
        broad.append(_prior_level(ib_prior, "ib_prior"))
    broad.extend(reversed(personal_levels))
    specific = list(personal_levels) + list(reversed(broad[:2] if len(broad) > 1 and broad[1].level == "ib_prior" else broad[:1]))
    # Preserve one exact deterministic order without duplicating personal rows.
    fallback_levels = list(personal_levels)
    if ib_prior.scope == "ib_subject_archetype":
        fallback_levels.append(_prior_level(ib_prior, "ib_prior"))
    fallback_levels.append(_prior_level(general_prior, "global_prior"))
    selected = fallback_levels[0]
    return FeatureHierarchy(
        selected=selected,
        specific_to_broad=tuple(fallback_levels),
        broad_to_specific=tuple(reversed(fallback_levels)),
        reference_date=reference_date,
    )
