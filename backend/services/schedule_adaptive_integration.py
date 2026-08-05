"""Failure-isolated bridge from deterministic recommendations to annotations."""

from __future__ import annotations

from datetime import date
import math
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from schemas.schedule_personalization import ModelType
from services.schedule_adaptive_ranking import LearnedCandidateSignal, SafeCandidateSnapshot
from services.schedule_model_registry import RegistryCompatibility, resolve_serving_model
from services.schedule_exploration import assign_near_tie_display
from services.schedule_explanations import build_structured_explanation
from services.schedule_personalization_config import (
    PersonalizationRuntimeConfig,
    personalization_runtime_config,
)
from services.schedule_personalization_serving import serve_personalization
from services.schedule_personalization_governance import get_or_create_private_consent


RERANKER_ALGORITHM_VERSION = "scheduling-safe-reranker.v1"
RERANKER_FEATURE_VERSION = "scheduling-reranker-feature.v1"
RERANKER_LABEL_VERSION = "scheduling-reranker-label.v1"
RERANKER_CALIBRATION_VERSION = "scheduling-reranker-calibration.v1"


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _candidate_snapshot(values: Iterable[dict[str, Any]], hard_deadline: Optional[date]) -> tuple[SafeCandidateSnapshot, ...]:
    snapshots = []
    for rank, item in enumerate(values, start=1):
        local_date = date.fromisoformat(str(item["date"]))
        snapshots.append(SafeCandidateSnapshot(
            candidate_id=f"date:{local_date.isoformat()}",
            local_date=local_date,
            deterministic_score=_finite(item.get("score")),
            baseline_rank=rank,
            reason_codes=tuple(str(code)[:96] for code in (item.get("reason_codes") or [])[:32]) or ("deterministic_safe",),
            hard_constraint_proof=("candidate_generated_by_deterministic_scheduler", "capacity", "deadline", "dependencies"),
            effort_minutes=max(1, min(100_800, int(round(_finite(item.get("recommended_effort_hours"), 1) * 60)))),
            deadline_critical=bool(hard_deadline and local_date >= hard_deadline),
        ))
    return tuple(snapshots)


def _artifact_predictor(model):
    artifact = dict(model.artifact_json or {})
    by_rank = artifact.get("adjustment_by_baseline_rank") or {}
    by_weekday = artifact.get("adjustment_by_weekday") or {}
    maturity = max(0.0, min(1.0, _finite(artifact.get("maturity"))))
    calibration = max(0.0, min(1.0, _finite(artifact.get("calibration_factor"))))
    eligible_decisions = max(0, min(1_000_000, int(_finite(artifact.get("eligible_decision_count")))))
    p50 = int(_finite(artifact.get("estimate_p50_minutes"))) or None
    p90 = int(_finite(artifact.get("estimate_p90_minutes"))) or None

    def predict(candidates: tuple[SafeCandidateSnapshot, ...]):
        return tuple(LearnedCandidateSignal(
            candidate_id=candidate.candidate_id,
            raw_adjustment=_finite(by_rank.get(str(candidate.baseline_rank))) + _finite(by_weekday.get(str(candidate.local_date.weekday()))),
            model_version=model.model_id,
            maturity=maturity,
            calibration_factor=calibration,
            eligible_decision_count=eligible_decisions,
            evidence_categories=("eligible_decision_history",),
            estimate_p50_minutes=p50,
            estimate_p90_minutes=p90,
        ) for candidate in candidates)

    return predict


def annotate_deterministic_recommendations(
    db: Session,
    *,
    user_id: int,
    recommendations: Iterable[dict[str, Any]],
    context_identity: str,
    hard_deadline: Optional[date],
    config: PersonalizationRuntimeConfig = personalization_runtime_config,
) -> dict[str, Any]:
    """Return additive annotations; never modify the supplied recommendation list."""
    deterministic = tuple(dict(item) for item in recommendations)
    candidates = _candidate_snapshot(deterministic, hard_deadline)
    compatibility = RegistryCompatibility(
        algorithm_version=RERANKER_ALGORITHM_VERSION,
        feature_schema_version=RERANKER_FEATURE_VERSION,
        label_version=RERANKER_LABEL_VERSION,
        calibration_version=RERANKER_CALIBRATION_VERSION,
    )
    resolution = resolve_serving_model(
        db,
        user_id=user_id,
        model_type=ModelType.reranker,
        scope="personal",
        compatibility=compatibility,
    )
    model = resolution.model
    result = serve_personalization(
        db,
        user_id=user_id,
        candidates=candidates,
        predictor=_artifact_predictor(model) if model is not None else None,
        model=model,
        context_identity=context_identity,
        config=config,
    )
    consent = get_or_create_private_consent(db, user_id)
    exploration = assign_near_tie_display(
        candidates,
        result.ranking,
        enabled=config.effective_exploration_enabled,
        consent_enabled=bool(consent.near_tie_exploration_enabled),
        near_tie_score_delta=config.near_tie_score_delta,
    )
    display_order = exploration.display_order if exploration.randomized else result.ranking.display_order
    projection = {
        "schema_version": result.schema_version,
        "serving_mode": result.mode.value,
        "model_version": model.model_id if model is not None else None,
        "baseline_order": list(result.ranking.baseline_order),
        "display_order": list(display_order),
        "fallback_reason": result.fallback_reason or resolution.fallback_reason,
        "latency_ms": result.latency_ms,
        "annotations": [{
            "candidate_id": item.candidate_id,
            "baseline_rank": item.baseline_rank,
            "personalized_rank": item.personalized_rank,
            "deterministic_score": item.deterministic_score,
            "learned_adjustment": item.applied_adjustment,
            "estimate_p50_minutes": item.estimate_p50_minutes,
            "estimate_p90_minutes": item.estimate_p90_minutes,
            "maturity": item.maturity,
            "calibration_factor": item.calibration_factor,
            "evidence_categories": list(item.evidence_categories),
        } for item in result.ranking.annotations],
        "exploration": {
            "schema_version": exploration.schema_version,
            "randomized": exploration.randomized,
            "eligible_candidate_ids": list(exploration.eligible_candidate_ids),
            "assignment_probability": exploration.assignment_probability,
            "assignment_denominator": exploration.assignment_denominator,
            "exclusion_reason": exploration.exclusion_reason,
        },
        "authority": {
            "feasibility": "deterministic_scheduler",
            "apply_order": "deterministic_baseline",
            "learned_auto_apply": False,
        },
    }
    projection["explanations"] = {
        item["candidate_id"]: build_structured_explanation(
            deterministic[index],
            projection,
            candidate_id=item["candidate_id"],
        )
        for index, item in enumerate(projection["annotations"])
        if index < len(deterministic)
    }
    return projection
