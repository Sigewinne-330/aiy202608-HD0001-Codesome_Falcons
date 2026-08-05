"""Opt-in, identifier-free aggregate priors from structured sufficient statistics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from typing import Optional

from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingConsentSetting, SchedulingFeatureSnapshot
from schemas.schedule_personalization import TASK_TAXONOMY_VERSION
from services.schedule_features import SUFFICIENT_STATISTICS_VERSION
from services.schedule_taxonomy import resolve_effort_prior


AGGREGATE_PRIOR_SCHEMA_VERSION = "scheduling-aggregate-prior.v1"
_ALLOWED_SCOPE_TYPES = frozenset({"user_global", "user_subject", "user_archetype", "user_segment"})


@dataclass(frozen=True)
class AggregateCell:
    cell_key: str
    contributor_count: int
    effective_sample_size: float
    mean_log_minutes: float
    variance_log_minutes: float
    sufficient: bool


@dataclass(frozen=True)
class AggregatePriorSnapshot:
    schema_version: str
    aggregate_version: str
    taxonomy_version: str
    feature_schema_version: str
    reference_date: date
    minimum_cell_contributors: int
    cells: tuple[AggregateCell, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "aggregate_version": self.aggregate_version,
            "taxonomy_version": self.taxonomy_version,
            "feature_schema_version": self.feature_schema_version,
            "reference_date": self.reference_date.isoformat(),
            "minimum_cell_contributors": self.minimum_cell_contributors,
            "cells": [asdict(item) for item in self.cells],
            "contains_direct_identifiers": False,
            "contains_raw_text": False,
        }


@dataclass(frozen=True)
class ResolvedAggregatePrior:
    source: str
    cell_key: Optional[str]
    mean_log_minutes: float
    variance_log_minutes: float
    contributor_count: int
    aggregate_version: Optional[str]


def _cell_key(row: SchedulingFeatureSnapshot) -> Optional[str]:
    if row.scope_type not in _ALLOWED_SCOPE_TYPES:
        return None
    prefix = {
        "user_global": "global",
        "user_subject": "subject",
        "user_archetype": "archetype",
        "user_segment": "segment",
    }[row.scope_type]
    key = "*" if row.scope_type == "user_global" else str(row.scope_key)
    if not key or len(key) > 191:
        return None
    return f"{prefix}:{key}"


def materialize_aggregate_priors(
    db: Session,
    *,
    reference_date: date,
    enabled: bool,
    minimum_cell_contributors: int = 10,
    taxonomy_version: str = TASK_TAXONOMY_VERSION,
    feature_schema_version: str = SUFFICIENT_STATISTICS_VERSION,
) -> AggregatePriorSnapshot:
    if not 2 <= minimum_cell_contributors <= 10_000:
        raise ValueError("minimum cell contributors must be between 2 and 10000")
    grouped: dict[str, list[tuple[float, float, float]]] = {}
    if enabled:
        rows = db.query(SchedulingFeatureSnapshot, SchedulingConsentSetting).join(
            SchedulingConsentSetting,
            SchedulingConsentSetting.user_id == SchedulingFeatureSnapshot.user_id,
        ).filter(
            SchedulingFeatureSnapshot.reference_date <= reference_date,
            SchedulingFeatureSnapshot.feature_schema_version == feature_schema_version,
            SchedulingFeatureSnapshot.eligible_cross_user.is_(True),
            SchedulingFeatureSnapshot.invalidated_at.is_(None),
            SchedulingConsentSetting.cross_user_learning_enabled.is_(True),
            SchedulingFeatureSnapshot.source_eligibility_watermark == SchedulingConsentSetting.eligibility_watermark,
        ).order_by(
            SchedulingFeatureSnapshot.user_id.asc(),
            SchedulingFeatureSnapshot.scope_type.asc(),
            SchedulingFeatureSnapshot.scope_key.asc(),
            SchedulingFeatureSnapshot.reference_date.desc(),
            SchedulingFeatureSnapshot.id.desc(),
        ).all()
        seen = set()
        for row, _consent in rows:
            identity = (row.user_id, row.scope_type, row.scope_key)
            if identity in seen:
                continue
            seen.add(identity)
            cell_key = _cell_key(row)
            statistics = row.sufficient_statistics or {}
            try:
                weight = float(statistics.get("effective_sample_size", row.effective_sample_size or 0))
                mean = float(statistics["mean_log_minutes"])
                variance = float(statistics.get("variance_log_minutes", 0.25))
            except (KeyError, TypeError, ValueError):
                continue
            if not cell_key or not all(math.isfinite(value) for value in (weight, mean, variance)):
                continue
            if weight <= 0 or variance < 0:
                continue
            grouped.setdefault(cell_key, []).append((weight, mean, variance))

    cells = []
    for cell_key, contributions in sorted(grouped.items()):
        total_weight = sum(item[0] for item in contributions)
        mean = sum(weight * value for weight, value, _ in contributions) / total_weight
        variance = sum(
            weight * (item_variance + (value - mean) ** 2)
            for weight, value, item_variance in contributions
        ) / total_weight
        cells.append(AggregateCell(
            cell_key=cell_key,
            contributor_count=len(contributions),
            effective_sample_size=round(total_weight, 6),
            mean_log_minutes=round(mean, 8),
            variance_log_minutes=round(max(0.01, min(4.0, variance)), 8),
            sufficient=len(contributions) >= minimum_cell_contributors,
        ))
    version_payload = {
        "schema_version": AGGREGATE_PRIOR_SCHEMA_VERSION,
        "taxonomy_version": taxonomy_version,
        "feature_schema_version": feature_schema_version,
        "reference_date": reference_date.isoformat(),
        "minimum_cell_contributors": minimum_cell_contributors,
        "cells": [asdict(item) for item in cells],
    }
    aggregate_version = hashlib.sha256(json.dumps(
        version_payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return AggregatePriorSnapshot(
        schema_version=AGGREGATE_PRIOR_SCHEMA_VERSION,
        aggregate_version=aggregate_version,
        taxonomy_version=taxonomy_version,
        feature_schema_version=feature_schema_version,
        reference_date=reference_date,
        minimum_cell_contributors=minimum_cell_contributors,
        cells=tuple(cells),
    )


def resolve_aggregate_prior(
    snapshot: AggregatePriorSnapshot,
    *,
    subject: Optional[str],
    task_archetype: str,
) -> ResolvedAggregatePrior:
    by_key = {item.cell_key: item for item in snapshot.cells if item.sufficient}
    keys = []
    if subject and subject not in {"unknown", "mixed"} and task_archetype not in {"unknown", "mixed"}:
        keys.append(f"segment:{subject}|{task_archetype}")
    if subject and subject not in {"unknown", "mixed"}:
        keys.append(f"subject:{subject}")
    if task_archetype not in {"unknown", "mixed"}:
        keys.append(f"archetype:{task_archetype}")
    keys.append("global:*")
    for key in keys:
        cell = by_key.get(key)
        if cell:
            return ResolvedAggregatePrior(
                source="cross_user_aggregate",
                cell_key=key,
                mean_log_minutes=cell.mean_log_minutes,
                variance_log_minutes=cell.variance_log_minutes,
                contributor_count=cell.contributor_count,
                aggregate_version=snapshot.aggregate_version,
            )
    prior = resolve_effort_prior(task_archetype=task_archetype, subject=subject)
    return ResolvedAggregatePrior(
        source="versioned_product_prior",
        cell_key=None,
        mean_log_minutes=prior.log_mean,
        variance_log_minutes=prior.log_sigma ** 2,
        contributor_count=0,
        aggregate_version=None,
    )
