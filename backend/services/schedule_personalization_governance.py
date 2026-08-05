"""Eligibility watermarks and deletion lineage for scheduling evidence."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Type
from uuid import uuid4

from sqlalchemy.orm import Query, Session

from models.schedule_personalization import (
    SchedulingConsentRevision,
    SchedulingConsentSetting,
    SchedulingDecisionEvent,
    SchedulingFeatureSnapshot,
    SchedulingGovernanceJob,
    SchedulingMemoryEntry,
    SchedulingModelPrediction,
    SchedulingModelRegistry,
    SchedulingOutcomeLabel,
    SchedulingWorkEvent,
    SchedulingWorkSession,
)
from schemas.schedule_personalization import CONSENT_POLICY_VERSION, GovernanceJobStatus, GovernanceJobType


def utc_now_naive() -> datetime:
    """Return UTC without tzinfo for the application's UTC MySQL sessions."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class EligibilityAdvanceResult:
    watermark: int
    job_id: str
    repeated: bool


def consent_snapshot(row: SchedulingConsentSetting) -> dict:
    return {
        "operational_personalization_enabled": bool(row.operational_personalization_enabled),
        "work_session_capture_enabled": bool(row.work_session_capture_enabled),
        "llm_memory_enabled": bool(row.llm_memory_enabled),
        "cross_user_learning_enabled": bool(row.cross_user_learning_enabled),
        "near_tie_exploration_enabled": bool(row.near_tie_exploration_enabled),
        "raw_event_retention_days": int(row.raw_event_retention_days),
        "rebuild_after_reset_enabled": bool(row.rebuild_after_reset_enabled),
        "policy_version": row.policy_version,
        "version": int(row.version),
        "eligibility_watermark": int(row.eligibility_watermark),
    }


def get_or_create_private_consent(db: Session, user_id: int) -> SchedulingConsentSetting:
    row = db.query(SchedulingConsentSetting).filter_by(user_id=user_id).one_or_none()
    if row is not None:
        return row
    row = SchedulingConsentSetting(
        user_id=user_id,
        policy_version=CONSENT_POLICY_VERSION,
        version=1,
        eligibility_watermark=1,
    )
    db.add(row)
    db.flush()
    db.add(SchedulingConsentRevision(
        user_id=user_id,
        version=1,
        policy_version=CONSENT_POLICY_VERSION,
        settings_snapshot=consent_snapshot(row),
        change_source="private_default",
    ))
    db.flush()
    return row


def personal_eligibility_query(db: Session, model: Type, user_id: int) -> Query:
    consent = get_or_create_private_consent(db, user_id)
    query = db.query(model).filter(model.user_id == user_id)
    watermark_column = getattr(model, "eligibility_watermark", None)
    if watermark_column is None:
        watermark_column = getattr(model, "source_eligibility_watermark")
    query = query.filter(watermark_column == consent.eligibility_watermark)
    if hasattr(model, "invalidated_at"):
        query = query.filter(model.invalidated_at.is_(None))
    if hasattr(model, "eligible_personal"):
        query = query.filter(model.eligible_personal.is_(True))
    if model is SchedulingMemoryEntry:
        query = query.filter(
            SchedulingMemoryEntry.status == "current",
            SchedulingMemoryEntry.deleted_at.is_(None),
        )
    return query


def cross_user_eligibility_query(db: Session, model: Type, user_id: int) -> Query:
    consent = get_or_create_private_consent(db, user_id)
    if not consent.cross_user_learning_enabled:
        return db.query(model).filter(False)
    query = personal_eligibility_query(db, model, user_id)
    if hasattr(model, "eligible_cross_user"):
        query = query.filter(model.eligible_cross_user.is_(True))
    return query


def _invalidate_materialized_state(db: Session, user_id: int, now: datetime) -> None:
    for model in (
        SchedulingFeatureSnapshot,
        SchedulingModelRegistry,
        SchedulingModelPrediction,
        SchedulingMemoryEntry,
    ):
        db.query(model).filter(
            model.user_id == user_id,
            model.invalidated_at.is_(None),
        ).update({model.invalidated_at: now}, synchronize_session=False)


def _invalidate_raw_evidence(db: Session, user_id: int, now: datetime) -> None:
    for model in (SchedulingDecisionEvent, SchedulingWorkEvent, SchedulingOutcomeLabel):
        updates = {model.invalidated_at: now}
        if hasattr(model, "eligible_personal"):
            updates[getattr(model, "eligible_personal")] = False
        if hasattr(model, "eligible_cross_user"):
            updates[getattr(model, "eligible_cross_user")] = False
        db.query(model).filter(
            model.user_id == user_id,
            model.invalidated_at.is_(None),
        ).update(updates, synchronize_session=False)
    db.query(SchedulingWorkSession).filter(
        SchedulingWorkSession.user_id == user_id,
        SchedulingWorkSession.state.in_(["active", "paused"]),
    ).update({
        SchedulingWorkSession.state: "discarded",
        SchedulingWorkSession.active_key: None,
        SchedulingWorkSession.ended_at: now,
    }, synchronize_session=False)


def advance_eligibility_watermark(
    db: Session,
    user_id: int,
    *,
    reason: str,
    idempotency_key: str,
    invalidate_raw: bool = False,
) -> EligibilityAdvanceResult:
    existing = db.query(SchedulingGovernanceJob).filter_by(
        idempotency_key=idempotency_key
    ).one_or_none()
    if existing is not None:
        payload = existing.payload_json or {}
        return EligibilityAdvanceResult(
            watermark=int(payload.get("eligibility_watermark", 1)),
            job_id=existing.job_id,
            repeated=True,
        )

    consent = db.query(SchedulingConsentSetting).filter_by(user_id=user_id).with_for_update().one_or_none()
    if consent is None:
        consent = get_or_create_private_consent(db, user_id)
    consent.eligibility_watermark = int(consent.eligibility_watermark) + 1
    now = utc_now_naive()
    _invalidate_materialized_state(db, user_id, now)
    if invalidate_raw:
        _invalidate_raw_evidence(db, user_id, now)

    job = SchedulingGovernanceJob(
        job_id=str(uuid4()),
        idempotency_key=idempotency_key,
        user_id=user_id,
        job_type=GovernanceJobType.propagate_deletion.value,
        status=GovernanceJobStatus.pending.value,
        payload_json={
            "reason": reason[:64],
            "eligibility_watermark": int(consent.eligibility_watermark),
            "invalidate_raw": bool(invalidate_raw),
        },
        not_before=now,
    )
    db.add(job)
    db.flush()
    return EligibilityAdvanceResult(
        watermark=int(consent.eligibility_watermark),
        job_id=job.job_id,
        repeated=False,
    )


def invalidate_memory_entry(
    db: Session,
    user_id: int,
    memory_id: str,
    *,
    suppression_fingerprint: Optional[str] = None,
) -> Optional[SchedulingMemoryEntry]:
    row = db.query(SchedulingMemoryEntry).filter_by(
        user_id=user_id,
        memory_id=memory_id,
    ).one_or_none()
    if row is None:
        return None
    now = utc_now_naive()
    row.status = "deleted"
    row.deleted_at = row.deleted_at or now
    row.invalidated_at = row.invalidated_at or now
    if suppression_fingerprint:
        row.suppression_fingerprint = suppression_fingerprint[:64]
    db.flush()
    return row


def enqueue_governance_job(
    db: Session,
    *,
    idempotency_key: str,
    job_type: str,
    user_id: Optional[int],
    payload: dict,
) -> SchedulingGovernanceJob:
    existing = db.query(SchedulingGovernanceJob).filter_by(
        idempotency_key=idempotency_key
    ).one_or_none()
    if existing is not None:
        return existing
    job = SchedulingGovernanceJob(
        job_id=str(uuid4()),
        idempotency_key=idempotency_key,
        user_id=user_id,
        job_type=job_type,
        status=GovernanceJobStatus.pending.value,
        payload_json=payload,
        not_before=utc_now_naive(),
    )
    db.add(job)
    db.flush()
    return job
