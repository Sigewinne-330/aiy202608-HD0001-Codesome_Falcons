"""Portable export, model reset, deletion status, and account-delete hook."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from models.schedule_personalization import (
    SchedulingConsentRevision,
    SchedulingDecisionEvent,
    SchedulingFeatureSnapshot,
    SchedulingGovernanceJob,
    SchedulingMemoryEntry,
    SchedulingModelPrediction,
    SchedulingModelRegistry,
    SchedulingOutcomeLabel,
    SchedulingWorkEvent,
)
from schemas.schedule_personalization import (
    FEATURE_SCHEMA_VERSION,
    PersonalizationResetRequest,
)
from services.schedule_consent import ConsentVersionConflict, update_consent_settings
from schemas.schedule_personalization import ConsentSettingsUpdate
from services.schedule_personalization_governance import (
    advance_eligibility_watermark,
    enqueue_governance_job,
    get_or_create_private_consent,
    utc_now_naive,
)


EXPORT_SCHEMA_VERSION = "scheduling-personalization-export.v1"


def _json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json(item) for item in value]
    return value


def portable_personalization_export(db: Session, user_id: int) -> dict:
    consent = get_or_create_private_consent(db, user_id)
    revisions = db.query(SchedulingConsentRevision).filter_by(user_id=user_id).order_by(
        SchedulingConsentRevision.version.asc()
    ).all()
    decisions = db.query(SchedulingDecisionEvent).filter_by(user_id=user_id).order_by(
        SchedulingDecisionEvent.occurred_at.asc(), SchedulingDecisionEvent.id.asc()
    ).all()
    work_events = db.query(SchedulingWorkEvent).filter_by(user_id=user_id).order_by(
        SchedulingWorkEvent.effective_at.asc(), SchedulingWorkEvent.id.asc()
    ).all()
    labels = db.query(SchedulingOutcomeLabel).filter_by(user_id=user_id).order_by(
        SchedulingOutcomeLabel.outcome_cutoff_at.asc(), SchedulingOutcomeLabel.id.asc()
    ).all()
    memories = db.query(SchedulingMemoryEntry).filter_by(user_id=user_id).order_by(
        SchedulingMemoryEntry.id.asc()
    ).all()
    features = db.query(SchedulingFeatureSnapshot).filter_by(user_id=user_id).order_by(
        SchedulingFeatureSnapshot.reference_date.asc(), SchedulingFeatureSnapshot.id.asc()
    ).all()
    models = db.query(SchedulingModelRegistry).filter_by(user_id=user_id).order_by(
        SchedulingModelRegistry.id.asc()
    ).all()
    predictions = db.query(SchedulingModelPrediction).filter_by(user_id=user_id).order_by(
        SchedulingModelPrediction.id.asc()
    ).all()
    jobs = db.query(SchedulingGovernanceJob).filter_by(user_id=user_id).order_by(
        SchedulingGovernanceJob.id.asc()
    ).all()
    return _json({
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": utc_now_naive(),
        "settings": {
            "version": consent.version,
            "policy_version": consent.policy_version,
            "operational_personalization_enabled": bool(consent.operational_personalization_enabled),
            "work_session_capture_enabled": bool(consent.work_session_capture_enabled),
            "llm_memory_enabled": bool(consent.llm_memory_enabled),
            "cross_user_learning_enabled": bool(consent.cross_user_learning_enabled),
            "near_tie_exploration_enabled": bool(consent.near_tie_exploration_enabled),
            "raw_event_retention_days": consent.raw_event_retention_days,
            "rebuild_after_reset_enabled": bool(consent.rebuild_after_reset_enabled),
        },
        "consent_history": [{
            "version": row.version,
            "policy_version": row.policy_version,
            "settings": row.settings_snapshot,
            "change_source": row.change_source,
            "changed_at": row.changed_at,
        } for row in revisions],
        "decision_events": [{
            "decision_point_id": row.decision_point_id,
            "source": {"source_type": row.source_type, "source_id": row.source_id},
            "occurred_at": row.occurred_at,
            "local_date": row.local_date,
            "timezone": row.timezone,
            "context": row.context_snapshot,
            "candidates": row.candidate_snapshot,
            "displayed_candidate_ids": row.displayed_candidate_ids,
            "selected_candidate_id": row.selected_candidate_id,
            "policy_version": row.policy_version,
            "model_version": row.model_version,
            "eligible": bool(row.eligible_personal and row.invalidated_at is None),
        } for row in decisions if row.invalidated_at is None],
        "work_events": [{
            "event_id": row.event_id,
            "source": {"source_type": row.source_type, "source_id": row.source_id},
            "event_type": row.event_type,
            "effective_at": row.effective_at,
            "effective_local_date": row.effective_local_date,
            "timezone": row.timezone,
            "before_values": row.before_values,
            "after_values": row.after_values,
            "provenance": row.provenance,
            "confidence": row.confidence,
            "correction_of_event_id": row.correction_of_event_id,
            "eligible": bool(row.eligible_personal and row.invalidated_at is None),
        } for row in work_events if row.invalidated_at is None],
        "outcome_labels": [{
            "source": {"source_type": row.source_type, "source_id": row.source_id},
            "episode": row.episode,
            "derivation_version": row.derivation_version,
            "outcome_cutoff_at": row.outcome_cutoff_at,
            "active_minutes": float(row.active_minutes) if row.active_minutes is not None else None,
            "active_minutes_provenance": row.active_minutes_provenance,
            "progress_ratio": float(row.progress_ratio) if row.progress_ratio is not None else None,
            "terminal_state": row.terminal_state,
            "is_censored": bool(row.is_censored),
            "censoring_reason": row.censoring_reason,
            "confidence": row.label_confidence,
        } for row in labels if row.invalidated_at is None],
        "memories": [{
            "memory_id": row.memory_id,
            "tier": row.tier,
            "memory_key": row.memory_key,
            "value_json": row.value_json,
            "display_text": row.display_text,
            "source": row.source,
            "evidence_event_ids": row.evidence_event_ids,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "valid_from": row.valid_from,
            "valid_until": row.valid_until,
            "status": row.status,
        } for row in memories if row.deleted_at is None and row.invalidated_at is None],
        "deleted_memory_tombstones": [{
            "memory_id": row.memory_id,
            "status": row.status,
            "deleted_at": row.deleted_at,
        } for row in memories if row.deleted_at is not None],
        "feature_snapshots": [{
            "scope_type": row.scope_type,
            "scope_key": row.scope_key,
            "reference_date": row.reference_date,
            "feature_schema_version": row.feature_schema_version,
            "effective_sample_size": float(row.effective_sample_size),
            "statistics": row.sufficient_statistics,
        } for row in features if row.invalidated_at is None],
        "models": [{
            "model_id": row.model_id,
            "model_type": row.model_type,
            "lifecycle": row.lifecycle,
            "algorithm_version": row.algorithm_version,
            "feature_schema_version": row.feature_schema_version,
            "effective_sample_size": float(row.effective_sample_size),
            "artifact_json": row.artifact_json if row.invalidated_at is None else None,
            "evaluation_metrics": row.evaluation_metrics,
            "invalidated": row.invalidated_at is not None,
        } for row in models],
        "predictions": [{
            "prediction_id": row.prediction_id,
            "decision_point_id": row.decision_point_id,
            "prediction_type": row.prediction_type,
            "horizon_date": row.horizon_date,
            "p10": float(row.p10) if row.p10 is not None else None,
            "p50": float(row.p50) if row.p50 is not None else None,
            "p90": float(row.p90) if row.p90 is not None else None,
            "probability": float(row.probability) if row.probability is not None else None,
            "serving_mode": row.serving_mode,
        } for row in predictions if row.invalidated_at is None],
        "governance_operations": [{
            "type": row.job_type,
            "status": row.status,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
            "error_code": row.last_error_code,
        } for row in jobs],
    })


def reset_personalization_model(
    db: Session,
    user_id: int,
    data: PersonalizationResetRequest,
) -> SchedulingGovernanceJob:
    key = f"model-reset:{user_id}:{data.idempotency_key}"
    existing = db.query(SchedulingGovernanceJob).filter_by(idempotency_key=key).one_or_none()
    if existing is not None:
        return existing
    consent = get_or_create_private_consent(db, user_id)
    if data.expected_settings_version is not None and data.expected_settings_version != consent.version:
        raise ConsentVersionConflict("personalization settings changed; reload before reset")
    now = utc_now_naive()
    for model in (SchedulingFeatureSnapshot, SchedulingModelRegistry, SchedulingModelPrediction):
        db.query(model).filter(
            model.user_id == user_id,
            model.invalidated_at.is_(None),
        ).update({model.invalidated_at: now}, synchronize_session=False)
    db.query(SchedulingMemoryEntry).filter(
        SchedulingMemoryEntry.user_id == user_id,
        SchedulingMemoryEntry.tier == "llm_reflection",
        SchedulingMemoryEntry.invalidated_at.is_(None),
    ).update({
        SchedulingMemoryEntry.invalidated_at: now,
        SchedulingMemoryEntry.status: "dismissed",
    }, synchronize_session=False)
    update_consent_settings(db, user_id, ConsentSettingsUpdate(
        operational_personalization_enabled=bool(consent.operational_personalization_enabled),
        work_session_capture_enabled=bool(consent.work_session_capture_enabled),
        llm_memory_enabled=bool(consent.llm_memory_enabled),
        cross_user_learning_enabled=bool(consent.cross_user_learning_enabled),
        near_tie_exploration_enabled=bool(consent.near_tie_exploration_enabled),
        raw_event_retention_days=int(consent.raw_event_retention_days),
        rebuild_after_reset_enabled=data.rebuild_from_retained_evidence,
        expected_version=int(consent.version),
        policy_version=consent.policy_version,
    ))
    job = enqueue_governance_job(
        db,
        idempotency_key=key,
        job_type="propagate_deletion",
        user_id=user_id,
        payload={
            "target": "derived_personalization",
            "rebuild_from_retained_evidence": data.rebuild_from_retained_evidence,
            "raw_evidence_preserved": True,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
        },
    )
    if data.rebuild_from_retained_evidence:
        enqueue_governance_job(
            db,
            idempotency_key=f"{key}:rebuild",
            job_type="refresh_features",
            user_id=user_id,
            payload={"reason": "model_reset_rebuild"},
        )
    return job


def prepare_personalization_account_deletion(
    db: Session,
    user_id: int,
    *,
    idempotency_key: str,
) -> SchedulingGovernanceJob:
    result = advance_eligibility_watermark(
        db,
        user_id,
        reason="account_deletion",
        idempotency_key=f"account-delete:{user_id}:{idempotency_key}",
        invalidate_raw=True,
    )
    return db.query(SchedulingGovernanceJob).filter_by(job_id=result.job_id).one()


def deletion_status(db: Session, user_id: int) -> dict:
    rows = db.query(SchedulingGovernanceJob).filter(
        SchedulingGovernanceJob.user_id == user_id,
        SchedulingGovernanceJob.job_type.in_(["propagate_deletion", "recompute_aggregate"]),
    ).order_by(SchedulingGovernanceJob.id.desc()).limit(100).all()
    return {
        "state": (
            "failed" if any(row.status == "failed" for row in rows)
            else "pending" if any(row.status in {"pending", "leased"} for row in rows)
            else "complete"
        ),
        "operations": [{
            "type": row.job_type,
            "status": row.status,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
            "error_code": row.last_error_code,
            "recoverable": row.status in {"pending", "leased", "failed"},
        } for row in rows],
    }
