"""Ordered work-session and source-event state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingWorkEvent, SchedulingWorkSession
from schemas.schedule_personalization import (
    EvidenceConfidence,
    OutcomeObservationInput,
    WorkEventInput,
    WorkEventType,
)
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_source_access import owned_schedule_source


TIMER_EVENTS = {
    WorkEventType.started,
    WorkEventType.paused,
    WorkEventType.resumed,
    WorkEventType.stopped,
}
TERMINAL_SOURCE_EVENTS = {
    WorkEventType.completed,
    WorkEventType.abandoned,
    WorkEventType.deleted,
}


class WorkEventError(ValueError):
    pass


class WorkEventNotFound(WorkEventError):
    pass


class WorkEventConflict(WorkEventError):
    pass


class WorkEventStale(WorkEventConflict):
    pass


class WorkEventRateLimited(WorkEventError):
    pass


@dataclass(frozen=True)
class WorkEventResult:
    event: Optional[SchedulingWorkEvent]
    session: Optional[SchedulingWorkSession]
    created: bool
    skipped_reason: Optional[str] = None


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _now_naive(now: Optional[datetime]) -> datetime:
    return _utc_naive(now or datetime.now(timezone.utc))


def _local_date(value: datetime, timezone_name: str) -> date:
    aware = value.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(timezone_name)).date()


def split_interval_by_local_date(
    start_at: datetime,
    end_at: datetime,
    timezone_name: str,
) -> list[tuple[date, int]]:
    """Split one factual UTC interval at local-midnight feature boundaries."""
    start = _utc_naive(start_at).replace(tzinfo=timezone.utc)
    end = _utc_naive(end_at).replace(tzinfo=timezone.utc)
    if end < start:
        raise WorkEventStale("interval end precedes its start")
    zone = ZoneInfo(timezone_name)
    cursor = start
    pieces: list[tuple[date, int]] = []
    while cursor < end:
        local_cursor = cursor.astimezone(zone)
        next_local_midnight = datetime.combine(
            local_cursor.date() + timedelta(days=1),
            time.min,
            tzinfo=zone,
        )
        boundary = min(end, next_local_midnight.astimezone(timezone.utc))
        pieces.append((local_cursor.date(), int((boundary - cursor).total_seconds())))
        cursor = boundary
    return pieces


def _event_payload_matches(event: SchedulingWorkEvent, data: WorkEventInput) -> bool:
    expected_after = dict(data.after_values)
    if data.progress_ratio is not None:
        expected_after["progress_ratio"] = data.progress_ratio
    if data.active_minutes is not None:
        expected_after["active_minutes"] = data.active_minutes
    if data.exertion is not None:
        expected_after["exertion"] = data.exertion
    if data.reason_code is not None:
        expected_after["reason_code"] = data.reason_code
    return (
        event.source_type == data.source.source_type
        and event.source_id == data.source.source_id
        and event.event_type == data.event_type.value
        and all((event.before_values or {}).get(key) == value for key, value in data.before_values.items())
        and all((event.after_values or {}).get(key) == value for key, value in expected_after.items())
        and event.provenance == data.provenance.value
        and event.confidence == data.confidence.value
        and (data.effective_at is None or event.effective_at == _utc_naive(data.effective_at))
        and event.correction_of_event_id == (
            str(data.correction_of_event_id) if data.correction_of_event_id else None
        )
    )


def _existing_idempotent(db: Session, user_id: int, data: WorkEventInput) -> Optional[WorkEventResult]:
    event = db.query(SchedulingWorkEvent).filter_by(
        user_id=user_id,
        idempotency_key=data.idempotency_key,
    ).one_or_none()
    if event is None:
        return None
    if not _event_payload_matches(event, data):
        raise WorkEventConflict("idempotency key was replayed with different event content")
    session = db.query(SchedulingWorkSession).filter_by(id=event.session_id).one_or_none() if event.session_id else None
    return WorkEventResult(event=event, session=session, created=False)


def _session_for_update(
    db: Session,
    user_id: int,
    public_id: str,
    data: WorkEventInput,
) -> SchedulingWorkSession:
    session = db.query(SchedulingWorkSession).filter(
        SchedulingWorkSession.public_id == public_id,
        SchedulingWorkSession.user_id == user_id,
    ).with_for_update().one_or_none()
    if session is None or session.source_type != data.source.source_type or session.source_id != data.source.source_id:
        raise WorkEventNotFound("work session does not exist or is not accessible")
    return session


def _last_effective_at(db: Session, session: SchedulingWorkSession) -> datetime:
    event = db.query(SchedulingWorkEvent).filter_by(session_id=session.id).order_by(
        SchedulingWorkEvent.effective_at.desc(),
        SchedulingWorkEvent.id.desc(),
    ).first()
    return event.effective_at if event else session.started_at


def _accrue_active(session: SchedulingWorkSession, effective_at: datetime) -> None:
    if session.current_interval_started_at is None:
        return
    if effective_at < session.current_interval_started_at:
        raise WorkEventStale("event precedes the current active interval")
    session.accumulated_active_seconds = int(session.accumulated_active_seconds or 0) + int(
        (effective_at - session.current_interval_started_at).total_seconds()
    )
    session.current_interval_started_at = None


def apply_work_event(
    db: Session,
    user_id: int,
    data: WorkEventInput,
    *,
    session_public_id: Optional[str] = None,
    server_now: Optional[datetime] = None,
    discard_open_interval: bool = False,
    capture_enabled: bool = True,
    rate_limit_per_minute: Optional[int] = 120,
) -> WorkEventResult:
    """Validate and append one event; the caller owns the final commit."""
    if owned_schedule_source(db, user_id, data.source.source_type, data.source.source_id) is None:
        raise WorkEventNotFound("schedule source does not exist or is not accessible")
    existing = _existing_idempotent(db, user_id, data)
    if existing is not None:
        return existing
    if not capture_enabled:
        return WorkEventResult(None, None, False, "capture_disabled")

    consent = get_or_create_private_consent(db, user_id)
    if not consent.operational_personalization_enabled:
        return WorkEventResult(None, None, False, "consent_disabled")
    if data.event_type in TIMER_EVENTS and not consent.work_session_capture_enabled:
        return WorkEventResult(None, None, False, "work_capture_disabled")

    now = _now_naive(server_now)
    if rate_limit_per_minute is not None:
        recent_count = db.query(SchedulingWorkEvent).filter(
            SchedulingWorkEvent.user_id == user_id,
            SchedulingWorkEvent.occurred_at >= now - timedelta(minutes=1),
        ).count()
        if recent_count >= rate_limit_per_minute:
            raise WorkEventRateLimited("work event rate limit exceeded")
    effective_at = _utc_naive(data.effective_at) if data.effective_at else now
    if effective_at > now + timedelta(minutes=5):
        raise WorkEventStale("effective time is implausibly in the future")

    if data.event_type == WorkEventType.corrected:
        if data.correction_of_event_id is None:
            raise WorkEventConflict("a correction must reference the corrected event")
        corrected = db.query(SchedulingWorkEvent).filter_by(
            event_id=str(data.correction_of_event_id),
            user_id=user_id,
            source_type=data.source.source_type,
            source_id=data.source.source_id,
        ).one_or_none()
        if corrected is None:
            raise WorkEventNotFound("corrected event does not exist or is not accessible")

    session: Optional[SchedulingWorkSession] = None
    before_state: Optional[str] = None
    if data.event_type == WorkEventType.started:
        if session_public_id is not None:
            raise WorkEventConflict("start does not accept an existing session")
        active_key = f"{user_id}:{data.source.source_type}:{data.source.source_id}"
        active = db.query(SchedulingWorkSession).filter_by(active_key=active_key).one_or_none()
        if active is not None:
            raise WorkEventConflict("an active or paused session already exists for this source")
        session = SchedulingWorkSession(
            public_id=str(uuid4()),
            user_id=user_id,
            source_type=data.source.source_type,
            source_id=data.source.source_id,
            active_key=active_key,
            state="active",
            timezone=data.after_values.get("timezone", "Asia/Shanghai"),
            started_at=effective_at,
            current_interval_started_at=effective_at,
        )
        db.add(session)
        db.flush()
    elif data.event_type in {WorkEventType.paused, WorkEventType.resumed, WorkEventType.stopped}:
        if not session_public_id:
            raise WorkEventConflict("session identifier is required for timer transitions")
        session = _session_for_update(db, user_id, session_public_id, data)
        before_state = session.state
        if effective_at < _last_effective_at(db, session):
            raise WorkEventStale("timer event is older than the current session state")
        if data.event_type == WorkEventType.paused:
            if session.state != "active":
                raise WorkEventConflict("only an active session can be paused")
            _accrue_active(session, effective_at)
            session.state = "paused"
            session.paused_at = effective_at
        elif data.event_type == WorkEventType.resumed:
            if session.state != "paused":
                raise WorkEventConflict("only a paused session can be resumed")
            session.state = "active"
            session.current_interval_started_at = effective_at
            session.paused_at = None
        else:
            if session.state not in {"active", "paused"}:
                raise WorkEventConflict("only an open session can be stopped")
            if session.state == "active" and not discard_open_interval:
                _accrue_active(session, effective_at)
            session.current_interval_started_at = None
            session.state = "discarded" if discard_open_interval else "stopped"
            session.active_key = None
            session.ended_at = effective_at
    elif session_public_id:
        session = _session_for_update(db, user_id, session_public_id, data)

    if data.event_type in TERMINAL_SOURCE_EVENTS and session is None:
        active_key = f"{user_id}:{data.source.source_type}:{data.source.source_id}"
        session = db.query(SchedulingWorkSession).filter_by(active_key=active_key).with_for_update().one_or_none()
        if session:
            before_state = session.state
            if session.state == "active":
                _accrue_active(session, effective_at)
            session.state = "stopped"
            session.active_key = None
            session.current_interval_started_at = None
            session.ended_at = effective_at

    timezone_name = session.timezone if session else data.after_values.get("timezone", "Asia/Shanghai")
    after_values = dict(data.after_values)
    if data.progress_ratio is not None:
        after_values["progress_ratio"] = data.progress_ratio
    if data.active_minutes is not None:
        after_values["active_minutes"] = data.active_minutes
    if data.exertion is not None:
        after_values["exertion"] = data.exertion
    if data.reason_code is not None:
        after_values["reason_code"] = data.reason_code
    if session is not None:
        after_values.update({
            "session_state": session.state,
            "accumulated_active_seconds": int(session.accumulated_active_seconds or 0),
        })
    before_values = dict(data.before_values)
    if before_state is not None:
        before_values.setdefault("session_state", before_state)

    event = SchedulingWorkEvent(
        event_id=str(uuid4()),
        user_id=user_id,
        session_id=session.id if session else None,
        source_type=data.source.source_type,
        source_id=data.source.source_id,
        event_type=data.event_type.value,
        idempotency_key=data.idempotency_key,
        occurred_at=now,
        effective_at=effective_at,
        effective_local_date=_local_date(effective_at, timezone_name),
        timezone=timezone_name,
        before_values=before_values,
        after_values=after_values,
        provenance=data.provenance.value,
        confidence=data.confidence.value,
        correction_of_event_id=str(data.correction_of_event_id) if data.correction_of_event_id else None,
        consent_version=consent.version,
        event_schema_version=data.event_schema_version,
        eligible_personal=True,
        eligible_cross_user=bool(consent.cross_user_learning_enabled),
        eligibility_watermark=consent.eligibility_watermark,
        retention_expires_at=effective_at + timedelta(days=int(consent.raw_event_retention_days)),
    )
    db.add(event)
    db.flush()
    if session is not None:
        session.last_event_id = event.event_id
        session.version = int(session.version or 1) + 1
    return WorkEventResult(event=event, session=session, created=True)


def reconcile_work_session(
    db: Session,
    user_id: int,
    session_public_id: str,
    *,
    effective_at: datetime,
    idempotency_key: str,
    action: str,
    server_now: Optional[datetime] = None,
    capture_enabled: bool = True,
) -> WorkEventResult:
    if action not in {"stop", "discard"}:
        raise WorkEventConflict("reconciliation action must be stop or discard")
    session = db.query(SchedulingWorkSession).filter_by(
        public_id=session_public_id,
        user_id=user_id,
    ).one_or_none()
    if session is None:
        raise WorkEventNotFound("work session does not exist or is not accessible")
    data = WorkEventInput(
        event_type=WorkEventType.stopped,
        source={"source_type": session.source_type, "source_id": session.source_id},
        idempotency_key=idempotency_key,
        effective_at=effective_at,
        reason_code="forgotten_timer_reconciliation",
        after_values={"reconciliation_action": action},
        provenance="active_timer",
        confidence=EvidenceConfidence.low,
    )
    return apply_work_event(
        db,
        user_id,
        data,
        session_public_id=session_public_id,
        server_now=server_now,
        discard_open_interval=action == "discard",
        capture_enabled=capture_enabled,
    )


def record_outcome_observation(
    db: Session,
    user_id: int,
    data: OutcomeObservationInput,
    *,
    server_now: Optional[datetime] = None,
    capture_enabled: bool = True,
) -> WorkEventResult:
    event_type = {
        "completed": WorkEventType.completed,
        "reasonably_abandoned": WorkEventType.abandoned,
        "deleted": WorkEventType.deleted,
        "confirmed_miss": WorkEventType.outcome_observed,
        "unknown": WorkEventType.outcome_observed,
    }[data.terminal_state.value]
    if data.correction_of_event_id is not None:
        event_type = WorkEventType.corrected
    event = WorkEventInput(
        event_type=event_type,
        source=data.source,
        idempotency_key=data.idempotency_key,
        effective_at=data.completed_at,
        progress_ratio=data.progress_ratio,
        active_minutes=data.actual_active_minutes,
        reason_code=data.reason_code,
        after_values={"terminal_state": data.terminal_state.value},
        provenance=data.provenance,
        confidence=data.confidence,
        correction_of_event_id=data.correction_of_event_id,
    )
    return apply_work_event(
        db,
        user_id,
        event,
        server_now=server_now,
        capture_enabled=capture_enabled,
    )
