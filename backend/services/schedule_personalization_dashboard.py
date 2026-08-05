"""User-scoped, privacy-safe projection for the personalization dashboard."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from models.schedule_personalization import (
    SchedulingFeatureSnapshot,
    SchedulingMemoryEntry,
    SchedulingModelPrediction,
    SchedulingModelRegistry,
    SchedulingOutcomeLabel,
)
from services.schedule_consent import consent_settings_payload
from services.schedule_personalization_config import PersonalizationRuntimeConfig
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_personalization_operations import serving_version_history


DASHBOARD_SCHEMA_VERSION = "scheduling-personalization-dashboard.v1"
CALIBRATION_MINIMUM_N = 20


def _float(value):
    return float(value) if value is not None else None


def personalization_dashboard(
    db: Session,
    user_id: int,
    config: PersonalizationRuntimeConfig,
) -> dict[str, Any]:
    consent = get_or_create_private_consent(db, user_id)
    watermark = int(consent.eligibility_watermark)
    prediction = db.query(SchedulingModelPrediction).filter(
        SchedulingModelPrediction.user_id == user_id,
        SchedulingModelPrediction.eligibility_watermark == watermark,
        SchedulingModelPrediction.invalidated_at.is_(None),
    ).order_by(SchedulingModelPrediction.id.desc()).first()
    outcomes = db.query(SchedulingOutcomeLabel).filter(
        SchedulingOutcomeLabel.user_id == user_id,
        SchedulingOutcomeLabel.eligibility_watermark == watermark,
        SchedulingOutcomeLabel.invalidated_at.is_(None),
        SchedulingOutcomeLabel.eligible_personal.is_(True),
        SchedulingOutcomeLabel.active_minutes.isnot(None),
    ).order_by(SchedulingOutcomeLabel.derived_at.desc(), SchedulingOutcomeLabel.id.desc()).limit(20).all()
    memories = db.query(SchedulingMemoryEntry).filter(
        SchedulingMemoryEntry.user_id == user_id,
        SchedulingMemoryEntry.eligibility_watermark == watermark,
        SchedulingMemoryEntry.invalidated_at.is_(None),
        SchedulingMemoryEntry.deleted_at.is_(None),
        SchedulingMemoryEntry.status == "current",
    ).all()
    features = db.query(SchedulingFeatureSnapshot).filter(
        SchedulingFeatureSnapshot.user_id == user_id,
        SchedulingFeatureSnapshot.source_eligibility_watermark == watermark,
        SchedulingFeatureSnapshot.invalidated_at.is_(None),
    ).order_by(SchedulingFeatureSnapshot.reference_date.desc(), SchedulingFeatureSnapshot.id.desc()).all()
    latest_by_scope = {}
    for row in features:
        latest_by_scope.setdefault((row.scope_type, row.scope_key), row)
    models = db.query(SchedulingModelRegistry).filter(
        SchedulingModelRegistry.user_id == user_id,
        SchedulingModelRegistry.source_eligibility_watermark == watermark,
        SchedulingModelRegistry.invalidated_at.is_(None),
    ).order_by(SchedulingModelRegistry.id.desc()).all()
    active_model = next((row for row in models if row.lifecycle == "promoted"), None)
    evaluation = (active_model.evaluation_metrics or {}) if active_model else {}
    calibration_n = int(evaluation.get("risk_n") or evaluation.get("n") or 0)
    calibration_value = evaluation.get("risk_ece", evaluation.get("expected_calibration_error"))
    memory_counts = Counter(row.tier for row in memories)
    evidence_count = sum(int(row.evidence_count or 0) for row in memories)
    trend = []
    for row in reversed(outcomes):
        actual = _float(row.active_minutes)
        ratio = _float(row.planned_actual_ratio)
        estimated = round(actual / ratio, 2) if actual and ratio and ratio > 0 else None
        trend.append({
            "date": row.derived_at.date().isoformat() if row.derived_at else None,
            "estimated_minutes": estimated,
            "actual_minutes": actual,
            "source_type": row.source_type,
            "terminal_state": row.terminal_state,
        })
    return {
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "privacy": consent_settings_payload(consent, config),
        "maturity": {
            "score": _float(prediction.evidence_maturity) if prediction else 0.0,
            "state": prediction.calibration_state if prediction else "cold_start",
            "effective_sample_size": round(sum(
                float(row.effective_sample_size or 0) for row in latest_by_scope.values()
            ), 2),
        },
        "effort_range": {
            "p50_minutes": _float(prediction.p50) if prediction else None,
            "p90_minutes": _float(prediction.p90) if prediction else None,
            "as_of": prediction.created_at if prediction else None,
        },
        "estimate_actual_trend": trend,
        "evidence": {
            "eligible_outcomes": len(outcomes),
            "memory_evidence_links": evidence_count,
            "feature_scopes": len(latest_by_scope),
            "memory_tiers": dict(sorted(memory_counts.items())),
        },
        "calibration": {
            "visible": calibration_n >= CALIBRATION_MINIMUM_N and calibration_value is not None,
            "minimum_n": CALIBRATION_MINIMUM_N,
            "n": calibration_n,
            "expected_calibration_error": (
                float(calibration_value)
                if calibration_n >= CALIBRATION_MINIMUM_N and calibration_value is not None
                else None
            ),
        },
        "model_history": serving_version_history(db, user_id=user_id, limit=20),
        "contains_cross_user_detail": False,
        "contains_raw_task_text": False,
    }
