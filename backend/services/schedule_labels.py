"""Versioned, cutoff-safe outcome label derivation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from models.schedule_personalization import (
    SchedulingDecisionEvent,
    SchedulingOutcomeLabel,
    SchedulingWorkEvent,
)
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_source_access import owned_schedule_source


LABEL_DERIVATION_VERSION = "scheduling-label.v1"


class LabelDerivationError(ValueError):
    pass


@dataclass(frozen=True)
class EffortEvidence:
    active_minutes: Optional[float]
    provenance: Optional[str]
    interval_complete: bool
    confidence: str


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _effective_events(events: Iterable[SchedulingWorkEvent]) -> list[SchedulingWorkEvent]:
    ordered = list(events)
    corrected_ids = {
        event.correction_of_event_id
        for event in ordered
        if event.event_type == "corrected" and event.correction_of_event_id
    }
    return [event for event in ordered if event.event_id not in corrected_ids]


def _timer_effort(events: list[SchedulingWorkEvent]) -> EffortEvidence:
    total_seconds = 0
    saw_timer = False
    all_closed = True
    confidence = "high"
    by_session: dict[int, list[SchedulingWorkEvent]] = {}
    timer_session_ids = {
        event.session_id
        for event in events
        if event.session_id and event.provenance == "active_timer"
    }
    for event in events:
        if event.session_id in timer_session_ids:
            by_session.setdefault(event.session_id, []).append(event)
    for session_events in by_session.values():
        active_start: Optional[datetime] = None
        saw_timer = True
        for event in sorted(session_events, key=lambda value: (value.effective_at, value.id)):
            if event.confidence == "low":
                confidence = "low"
            elif event.confidence == "medium" and confidence == "high":
                confidence = "medium"
            if event.event_type in {"started", "resumed"} and event.provenance == "active_timer":
                active_start = event.effective_at
            elif event.event_type == "paused" and event.provenance == "active_timer" and active_start is not None:
                total_seconds += max(0, int((event.effective_at - active_start).total_seconds()))
                active_start = None
            elif event.event_type in {"stopped", "completed", "abandoned", "deleted"}:
                if active_start is not None and (event.after_values or {}).get("session_state") != "discarded":
                    total_seconds += max(0, int((event.effective_at - active_start).total_seconds()))
                active_start = None
        if active_start is not None:
            all_closed = False
    if saw_timer:
        return EffortEvidence(
            active_minutes=total_seconds / 60.0,
            provenance="active_timer_measured" if confidence != "low" else "active_timer_low_confidence",
            interval_complete=all_closed,
            confidence=confidence,
        )
    manual = next(
        (
            event for event in reversed(events)
            if (event.after_values or {}).get("active_minutes") is not None
        ),
        None,
    )
    if manual is not None:
        return EffortEvidence(
            active_minutes=float(manual.after_values["active_minutes"]),
            provenance="user_reported_proxy",
            interval_complete=False,
            confidence=manual.confidence if manual.confidence in {"high", "medium", "low"} else "unknown",
        )
    return EffortEvidence(None, None, False, "unknown")


def _source_dates(source: object, source_type: str) -> tuple[Optional[date], Optional[date], float]:
    if source_type == "task":
        personal = getattr(source, "personal_deadline", None)
        hard = getattr(source, "hard_deadline_date", None) or getattr(source, "deadline", None)
    elif source_type == "subtask":
        personal = None
        hard = getattr(source, "hard_deadline_date", None) or getattr(source, "notice_time", None)
    else:
        personal = None
        hard = getattr(source, "due_date", None)
    if isinstance(personal, datetime):
        personal = personal.date()
    if isinstance(hard, datetime):
        hard = hard.date()
    return personal, hard, float(getattr(source, "estimated_hours", 0) or 0)


def _terminal(events: list[SchedulingWorkEvent]) -> tuple[str, Optional[SchedulingWorkEvent]]:
    for event in reversed(events):
        declared = (event.after_values or {}).get("terminal_state")
        if declared in {"completed", "reasonably_abandoned", "deleted", "confirmed_miss", "unknown"}:
            return declared, event
        mapped = {
            "completed": "completed",
            "abandoned": "reasonably_abandoned",
            "deleted": "deleted",
        }.get(event.event_type)
        if mapped:
            return mapped, event
    return "unknown", None


def derive_outcome_label(
    db: Session,
    user_id: int,
    source_type: str,
    source_id: int,
    *,
    outcome_cutoff_at: datetime,
    derivation_version: str = LABEL_DERIVATION_VERSION,
) -> SchedulingOutcomeLabel:
    source = owned_schedule_source(db, user_id, source_type, source_id)
    if source is None:
        raise LabelDerivationError("schedule source does not exist or is not accessible")
    cutoff = _utc_naive(outcome_cutoff_at)
    consent = get_or_create_private_consent(db, user_id)
    episode = 1 + db.query(SchedulingWorkEvent).filter(
        SchedulingWorkEvent.user_id == user_id,
        SchedulingWorkEvent.source_type == source_type,
        SchedulingWorkEvent.source_id == source_id,
        SchedulingWorkEvent.event_type == "reopened",
        SchedulingWorkEvent.effective_at <= cutoff,
        SchedulingWorkEvent.occurred_at <= cutoff,
        SchedulingWorkEvent.eligible_personal.is_(True),
        SchedulingWorkEvent.eligibility_watermark == consent.eligibility_watermark,
        SchedulingWorkEvent.invalidated_at.is_(None),
    ).count()
    existing = db.query(SchedulingOutcomeLabel).filter_by(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        episode=episode,
        derivation_version=derivation_version,
        outcome_cutoff_at=cutoff,
    ).one_or_none()
    if existing is not None:
        return existing

    events = db.query(SchedulingWorkEvent).filter(
        SchedulingWorkEvent.user_id == user_id,
        SchedulingWorkEvent.source_type == source_type,
        SchedulingWorkEvent.source_id == source_id,
        SchedulingWorkEvent.effective_at <= cutoff,
        SchedulingWorkEvent.occurred_at <= cutoff,
        SchedulingWorkEvent.eligible_personal.is_(True),
        SchedulingWorkEvent.eligibility_watermark == consent.eligibility_watermark,
        SchedulingWorkEvent.invalidated_at.is_(None),
    ).order_by(SchedulingWorkEvent.effective_at.asc(), SchedulingWorkEvent.id.asc()).all()
    events = _effective_events(events)
    effort = _timer_effort(events)
    terminal_state, terminal_event = _terminal(events)
    if terminal_event is None:
        is_censored = True
        censoring_reason = "still_open"
        censored_at = cutoff
    elif terminal_state == "unknown":
        is_censored = True
        censoring_reason = "offline_unknown"
        censored_at = terminal_event.effective_at
    else:
        is_censored = False
        censoring_reason = None
        censored_at = None

    progress_event = next(
        (event for event in reversed(events) if (event.after_values or {}).get("progress_ratio") is not None),
        None,
    )
    progress_ratio = float(progress_event.after_values["progress_ratio"]) if progress_event else None
    if terminal_state == "completed" and progress_ratio is None:
        progress_ratio = 1.0

    start_event = next((event for event in events if event.event_type == "started"), None)
    basis_times = [
        event.effective_at for event in events if event.event_type in {"created", "scheduled"}
    ]
    decision = db.query(SchedulingDecisionEvent).filter(
        SchedulingDecisionEvent.user_id == user_id,
        SchedulingDecisionEvent.source_type == source_type,
        SchedulingDecisionEvent.source_id == source_id,
        SchedulingDecisionEvent.occurred_at <= cutoff,
        SchedulingDecisionEvent.eligible_personal.is_(True),
        SchedulingDecisionEvent.eligibility_watermark == consent.eligibility_watermark,
        SchedulingDecisionEvent.invalidated_at.is_(None),
    ).order_by(SchedulingDecisionEvent.occurred_at.desc(), SchedulingDecisionEvent.id.desc()).first()
    if decision:
        basis_times.append(decision.occurred_at)
    basis = min(basis_times) if basis_times else None
    start_latency = None
    if basis and start_event and start_event.effective_at >= basis:
        start_latency = (start_event.effective_at - basis).total_seconds() / 60.0

    timezone_name = terminal_event.timezone if terminal_event else (events[-1].timezone if events else "Asia/Shanghai")
    completed_date = None
    if terminal_state == "completed" and terminal_event:
        completed_date = terminal_event.effective_at.replace(tzinfo=timezone.utc).astimezone(
            ZoneInfo(timezone_name)
        ).date()
    personal_date, hard_date, estimated_hours = _source_dates(source, source_type)
    active_provenance = effort.provenance
    if terminal_state == "completed" and effort.active_minutes is None:
        active_provenance = "completion_proxy_no_effort"
    label_confidence = effort.confidence
    if terminal_event and terminal_event.confidence in {"high", "medium", "low"}:
        rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
        if rank[terminal_event.confidence] > rank[label_confidence]:
            label_confidence = terminal_event.confidence

    label = SchedulingOutcomeLabel(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        decision_point_id=decision.decision_point_id if decision else None,
        episode=episode,
        derivation_version=derivation_version,
        outcome_cutoff_at=cutoff,
        active_minutes=effort.active_minutes,
        active_minutes_provenance=active_provenance,
        interval_complete=effort.interval_complete,
        start_latency_minutes=start_latency,
        planned_actual_ratio=(effort.active_minutes / 60.0 / estimated_hours) if effort.active_minutes is not None and estimated_hours > 0 else None,
        progress_ratio=progress_ratio,
        completed_before_personal_target=(completed_date <= personal_date) if completed_date and personal_date else None,
        completed_before_hard_deadline=(completed_date <= hard_date) if completed_date and hard_date else None,
        terminal_state=terminal_state,
        is_censored=is_censored,
        censoring_reason=censoring_reason,
        censored_at=censored_at,
        label_confidence=label_confidence,
        eligible_personal=bool(consent.operational_personalization_enabled),
        eligible_evaluation=label_confidence in {"high", "medium"},
        eligible_cross_user=bool(consent.cross_user_learning_enabled),
        eligibility_watermark=consent.eligibility_watermark,
    )
    db.add(label)
    if decision is not None:
        decision.outcome_link_status = "linked"
    db.flush()
    return label
