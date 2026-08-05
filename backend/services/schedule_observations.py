"""Typed, consent-aware scheduling observation ledger writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingDecisionEvent
from schemas.schedule_personalization import DecisionObservationInput
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_source_access import owned_schedule_source


ALLOWED_CONTEXT_KEYS = frozenset({
    "algorithm_version",
    "capacity_snapshot",
    "decision_kind",
    "input_revision",
    "intervention_id",
    "overload_count",
    "output_revision",
    "plan_id",
    "policy_profile",
    "requested_date",
    "selected_date",
    "source_schedule_version",
    "threshold",
    "trigger",
    "assignment_probability",
})


class DecisionObservationError(ValueError):
    """Base class for a rejected analytical observation."""


class DecisionObservationNotFound(DecisionObservationError):
    """The source does not exist or is not owned by the caller."""


class DecisionObservationConflict(DecisionObservationError):
    """A stable identity was replayed with different immutable content."""


@dataclass(frozen=True)
class DecisionCaptureResult:
    event: Optional[SchedulingDecisionEvent]
    created: bool
    skipped_reason: Optional[str] = None


def _json_value(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def canonical_context_hash(context_snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(
        context_snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_context(context_snapshot: dict[str, Any], expected_hash: str) -> dict[str, Any]:
    unknown = sorted(set(context_snapshot) - ALLOWED_CONTEXT_KEYS)
    if unknown:
        raise DecisionObservationError(f"context contains non-allowlisted keys: {', '.join(unknown)}")
    canonical = _json_value(context_snapshot)
    if canonical_context_hash(canonical) != expected_hash:
        raise DecisionObservationConflict("context hash does not match the canonical context snapshot")
    return canonical


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _immutable_payload(row: SchedulingDecisionEvent) -> dict[str, Any]:
    return {
        "source_type": row.source_type,
        "source_id": row.source_id,
        "local_date": row.local_date.isoformat(),
        "timezone": row.timezone,
        "event_schema_version": row.event_schema_version,
        "context_hash": row.context_hash,
        "context_snapshot": row.context_snapshot,
        "candidate_snapshot": row.candidate_snapshot,
        "displayed_candidate_ids": row.displayed_candidate_ids,
        "selected_candidate_id": row.selected_candidate_id,
        "selection_source": row.selection_source,
        "automation_mode": row.automation_mode,
        "action_propensity": float(row.action_propensity) if row.action_propensity is not None else None,
        "policy_version": row.policy_version,
        "model_version": row.model_version,
    }


def _input_payload(data: DecisionObservationInput, context_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_type": data.source.source_type,
        "source_id": data.source.source_id,
        "local_date": data.local_date.isoformat(),
        "timezone": data.timezone,
        "event_schema_version": data.event_schema_version,
        "context_hash": data.context_hash,
        "context_snapshot": context_snapshot,
        "candidate_snapshot": [candidate.model_dump(mode="json") for candidate in data.candidates],
        "displayed_candidate_ids": list(data.displayed_candidate_ids),
        "selected_candidate_id": data.selected_candidate_id,
        "selection_source": data.selection_source,
        "automation_mode": data.automation_mode,
        "action_propensity": data.action_propensity,
        "policy_version": data.policy_version,
        "model_version": data.model_version,
    }


def _matches(existing: SchedulingDecisionEvent, expected: dict[str, Any]) -> bool:
    return _json_value(_immutable_payload(existing)) == _json_value(expected)


def capture_decision_observation(
    db: Session,
    user_id: int,
    data: DecisionObservationInput,
    *,
    capture_enabled: bool = True,
) -> DecisionCaptureResult:
    """Persist one immutable observation; caller owns the surrounding commit."""
    if not capture_enabled:
        return DecisionCaptureResult(event=None, created=False, skipped_reason="capture_disabled")
    if owned_schedule_source(db, user_id, data.source.source_type, data.source.source_id) is None:
        raise DecisionObservationNotFound("schedule source does not exist or is not accessible")

    consent = get_or_create_private_consent(db, user_id)
    if not consent.operational_personalization_enabled:
        return DecisionCaptureResult(event=None, created=False, skipped_reason="consent_disabled")
    if data.consent_version is not None and data.consent_version != consent.version:
        raise DecisionObservationConflict("consent version changed before observation capture")
    if data.randomized_assignment and not consent.near_tie_exploration_enabled:
        raise DecisionObservationError("randomized assignment was not consent-eligible")

    context_snapshot = _validate_context(data.context_snapshot, data.context_hash)
    expected = _input_payload(data, context_snapshot)
    decision_point_id = str(data.decision_point_id)
    identity_filters = [SchedulingDecisionEvent.decision_point_id == decision_point_id]
    if data.idempotency_key:
        identity_filters.append(
            (SchedulingDecisionEvent.user_id == user_id)
            & (SchedulingDecisionEvent.idempotency_key == data.idempotency_key)
        )
    existing = db.query(SchedulingDecisionEvent).filter(or_(*identity_filters)).one_or_none()
    if existing is not None:
        if existing.user_id != user_id:
            raise DecisionObservationNotFound("schedule source does not exist or is not accessible")
        if not _matches(existing, expected):
            raise DecisionObservationConflict("decision identity was replayed with different content")
        return DecisionCaptureResult(event=existing, created=False)

    occurred_at = _utc_naive(data.occurred_at)
    retention_expires_at = occurred_at + timedelta(days=int(consent.raw_event_retention_days))
    row = SchedulingDecisionEvent(
        decision_point_id=decision_point_id,
        user_id=user_id,
        source_type=data.source.source_type,
        source_id=data.source.source_id,
        correlation_id=data.correlation_id,
        idempotency_key=data.idempotency_key,
        occurred_at=occurred_at,
        local_date=data.local_date,
        timezone=data.timezone,
        event_schema_version=data.event_schema_version,
        context_hash=data.context_hash,
        context_snapshot=context_snapshot,
        candidate_snapshot=expected["candidate_snapshot"],
        displayed_candidate_ids=expected["displayed_candidate_ids"],
        selected_candidate_id=data.selected_candidate_id,
        selection_source=data.selection_source,
        automation_mode=data.automation_mode,
        action_propensity=data.action_propensity if data.randomized_assignment else None,
        policy_version=data.policy_version,
        model_version=data.model_version,
        consent_version=consent.version,
        eligible_personal=True,
        eligible_cross_user=bool(consent.cross_user_learning_enabled),
        eligibility_watermark=consent.eligibility_watermark,
        retention_expires_at=retention_expires_at,
        outcome_link_status="unlisted_action" if data.selected_candidate_id and data.selected_candidate_id not in {
            candidate.candidate_id for candidate in data.candidates
        } else "pending",
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.query(SchedulingDecisionEvent).filter(or_(*identity_filters)).one_or_none()
        if existing is None or existing.user_id != user_id or not _matches(existing, expected):
            raise DecisionObservationConflict("concurrent decision capture conflicted")
        return DecisionCaptureResult(event=existing, created=False)
    return DecisionCaptureResult(event=row, created=True)
