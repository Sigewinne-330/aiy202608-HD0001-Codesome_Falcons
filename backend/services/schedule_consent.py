"""Server-authoritative, versioned personalization consent settings."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from models.schedule_personalization import (
    SchedulingConsentRevision,
    SchedulingDecisionEvent,
    SchedulingGovernanceJob,
    SchedulingOutcomeLabel,
    SchedulingWorkEvent,
    SchedulingWorkSession,
)
from schemas.schedule_personalization import (
    CONSENT_POLICY_VERSION,
    ConsentSettingsUpdate,
    GovernanceJobStatus,
    GovernanceJobType,
)
from services.schedule_personalization_config import PersonalizationRuntimeConfig
from services.schedule_personalization_governance import (
    advance_eligibility_watermark,
    consent_snapshot,
    get_or_create_private_consent,
)


class ConsentSettingsError(ValueError):
    pass


class ConsentVersionConflict(ConsentSettingsError):
    pass


SETTING_FIELDS = (
    "operational_personalization_enabled",
    "work_session_capture_enabled",
    "llm_memory_enabled",
    "cross_user_learning_enabled",
    "near_tie_exploration_enabled",
    "raw_event_retention_days",
    "rebuild_after_reset_enabled",
    "policy_version",
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enqueue_job(
    db: Session,
    user_id: int,
    *,
    job_type: str,
    idempotency_key: str,
    payload: dict,
) -> None:
    if db.query(SchedulingGovernanceJob).filter_by(idempotency_key=idempotency_key).first():
        return
    db.add(SchedulingGovernanceJob(
        job_id=str(uuid4()),
        idempotency_key=idempotency_key,
        user_id=user_id,
        job_type=job_type,
        status=GovernanceJobStatus.pending.value,
        payload_json=payload,
        not_before=_now(),
    ))


def _withdraw_cross_user(db: Session, user_id: int, version: int) -> None:
    for model in (SchedulingDecisionEvent, SchedulingWorkEvent, SchedulingOutcomeLabel):
        db.query(model).filter(
            model.user_id == user_id,
            model.eligible_cross_user.is_(True),
        ).update({model.eligible_cross_user: False}, synchronize_session=False)
    _enqueue_job(
        db,
        user_id,
        job_type=GovernanceJobType.recompute_aggregate.value,
        idempotency_key=f"consent:{user_id}:{version}:cross-user-withdrawal",
        payload={"reason": "cross_user_consent_withdrawn", "consent_version": version},
    )


def _discard_open_sessions(db: Session, user_id: int) -> None:
    now = _now()
    db.query(SchedulingWorkSession).filter(
        SchedulingWorkSession.user_id == user_id,
        SchedulingWorkSession.state.in_(["active", "paused"]),
    ).update({
        SchedulingWorkSession.state: "discarded",
        SchedulingWorkSession.active_key: None,
        SchedulingWorkSession.current_interval_started_at: None,
        SchedulingWorkSession.ended_at: now,
    }, synchronize_session=False)


def update_consent_settings(
    db: Session,
    user_id: int,
    data: ConsentSettingsUpdate,
):
    if data.policy_version != CONSENT_POLICY_VERSION:
        raise ConsentSettingsError("unsupported personalization consent policy version")
    row = get_or_create_private_consent(db, user_id)
    if data.expected_version is not None and data.expected_version != row.version:
        raise ConsentVersionConflict("personalization settings changed; reload before saving")

    requested = data.model_dump(exclude={"expected_version"})
    changed = any(getattr(row, field) != requested[field] for field in SETTING_FIELDS)
    if not changed:
        return row
    previous = consent_snapshot(row)
    next_version = int(row.version) + 1

    operational_withdrawn = (
        row.operational_personalization_enabled
        and not data.operational_personalization_enabled
    )
    cross_user_withdrawn = (
        row.cross_user_learning_enabled
        and not data.cross_user_learning_enabled
    )
    work_capture_withdrawn = (
        row.work_session_capture_enabled
        and not data.work_session_capture_enabled
    )
    retention_changed = row.raw_event_retention_days != data.raw_event_retention_days

    if operational_withdrawn:
        advance_eligibility_watermark(
            db,
            user_id,
            reason="operational_personalization_withdrawn",
            idempotency_key=f"consent:{user_id}:{next_version}:operational-withdrawal",
        )
    if cross_user_withdrawn:
        _withdraw_cross_user(db, user_id, next_version)
    if work_capture_withdrawn or operational_withdrawn:
        _discard_open_sessions(db, user_id)

    for field in SETTING_FIELDS:
        setattr(row, field, requested[field])
    row.version = next_version
    now = _now()
    if data.operational_personalization_enabled:
        row.accepted_at = row.accepted_at or now
        row.withdrawn_at = None
    else:
        row.withdrawn_at = now if operational_withdrawn else row.withdrawn_at

    db.add(SchedulingConsentRevision(
        user_id=user_id,
        version=next_version,
        policy_version=data.policy_version,
        settings_snapshot={
            **consent_snapshot(row),
            "previous_version": previous["version"],
        },
        change_source="user",
    ))
    if retention_changed:
        _enqueue_job(
            db,
            user_id,
            job_type=GovernanceJobType.enforce_retention.value,
            idempotency_key=f"consent:{user_id}:{next_version}:retention",
            payload={
                "consent_version": next_version,
                "retention_days": data.raw_event_retention_days,
            },
        )
    db.flush()
    return row


def consent_settings_payload(row, config: PersonalizationRuntimeConfig) -> dict:
    return {
        **consent_snapshot(row),
        "accepted_at": row.accepted_at,
        "withdrawn_at": row.withdrawn_at,
        "runtime": {
            "capture_enabled": config.effective_capture_enabled,
            "serving_mode": config.effective_serving_mode.value,
            "reflection_enabled": config.effective_reflection_enabled,
            "cross_user_enabled": config.effective_cross_user_enabled,
            "exploration_enabled": config.effective_exploration_enabled,
        },
        "effective": {
            "work_session_capture": bool(
                row.operational_personalization_enabled
                and row.work_session_capture_enabled
                and config.effective_capture_enabled
            ),
            "llm_memory": bool(
                row.operational_personalization_enabled
                and row.llm_memory_enabled
                and config.effective_reflection_enabled
            ),
            "cross_user_learning": bool(
                row.operational_personalization_enabled
                and row.cross_user_learning_enabled
                and config.effective_cross_user_enabled
            ),
            "near_tie_exploration": bool(
                row.operational_personalization_enabled
                and row.near_tie_exploration_enabled
                and config.effective_exploration_enabled
            ),
        },
        "deterministic_scheduling_available": True,
    }
