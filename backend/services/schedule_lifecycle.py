"""Transactional scheduling facade: preferences, interventions, plans, and audit."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.deadline import Deadline
from models.scheduling import (
    ScheduleAuditEvent,
    ScheduleAllocation,
    ScheduleCapacityOverride,
    ScheduleIntervention,
    SchedulePlan,
    SchedulePlanItem,
    SchedulingPreference,
)
from models.sub_task import SubTask
from models.task_new import Task, TaskType
from schemas.scheduling import (
    CapacityOverrideUpsert,
    InterventionResolveRequest,
    PlanCreateRequest,
    PlanApplyRequest,
    PreflightRequest,
    ScheduleDecision,
    ScheduleItemInput,
    ScheduleProfile,
    SchedulingPreferenceUpdate,
)
from services.schedule_engine import RecommendationResult, RebalanceResult, recommend_date, rebalance
from services.schedule_clarification import analyze_clarification_value, assumptions_from_effort_prior
from services.schedule_policy import ALGORITHM_VERSION, DEFAULT_PREFERENCES, INTERVENTION_THRESHOLD, profile_for
from services.schedule_projection import (
    ScheduleSnapshot,
    WorkItem,
    load_capacity_policy,
    load_snapshot,
    serialize_item,
)
from services.schedule_taxonomy import normalize_task_archetype, resolve_effort_prior


logger = logging.getLogger(__name__)


class ScheduleError(Exception):
    def __init__(self, detail: str, status_code: int = 409, code: str = "schedule_conflict"):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code


def _now() -> datetime:
    # Persist naive UTC for compatibility with the existing TIMESTAMP columns
    # while avoiding deprecated ``datetime.utcnow``.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


_AUDIT_METADATA_KEYS = {
    "projected_count", "state", "feature_snapshot", "deterministic_rank",
    "feasible", "idempotency_key", "trigger", "overloaded_dates",
    "notification_kind", "affected_count", "provider", "model",
    "total_tokens", "usage_purpose", "user_choice", "override", "outcome",
    "selected_date", "source_type", "source_id", "completion_state",
    "requested_date", "recommendation_energy_ratio", "alternative_count",
    "deterministic_score", "algorithm_version", "profile",
}
_AFFECTED_ITEM_KEYS = {
    "source_type", "source_id", "date", "before_date", "after_date",
    "effort_hours", "schedule_version",
}


def _sanitize_audit_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str):
        return value[:128]
    if isinstance(value, (list, tuple)):
        return [
            sanitized
            for item in list(value)[:50]
            if (sanitized := _sanitize_audit_value(item, depth=depth + 1)) is not None
        ]
    if isinstance(value, dict):
        return {
            key: sanitized
            for key, item in value.items()
            if key in _AUDIT_METADATA_KEYS
            if (sanitized := _sanitize_audit_value(item, depth=depth + 1)) is not None
        }
    return None


def sanitize_audit_metadata(metadata: Optional[dict]) -> dict:
    value = _sanitize_audit_value(metadata or {})
    return value if isinstance(value, dict) else {}


def sanitize_affected_items(items: Optional[list]) -> list[dict]:
    sanitized_items = []
    for item in (items or [])[:100]:
        if not isinstance(item, dict):
            continue
        sanitized = {
            key: value
            for key, raw in item.items()
            if key in _AFFECTED_ITEM_KEYS
            if (value := _sanitize_audit_value(raw, depth=1)) is not None
        }
        if sanitized:
            sanitized_items.append(sanitized)
    return sanitized_items


def sanitize_reason_codes(reason_codes: Optional[list]) -> list[str]:
    return [str(value)[:128] for value in (reason_codes or [])[:50]]


def _serialize_candidate(candidate) -> dict:
    return candidate.to_dict() if candidate else None


def _item_from_request(data: ScheduleItemInput, user_id: int) -> WorkItem:
    effort = data.estimated_hours
    return WorkItem(
        source_type=data.source_type.value,
        source_id=data.source_id or 0,
        user_id=user_id,
        title=data.title,
        local_date=data.target_date,
        status="todo",
        priority=data.priority,
        estimated_hours=float(effort if effort is not None else 1.0),
        energy_intensity=float(data.energy_intensity),
        effort_source=data.effort_source,
        is_schedule_locked=data.is_schedule_locked,
        schedule_kind=data.schedule_kind or data.source_type.value,
        hard_deadline_date=data.hard_deadline_date,
        earliest_start_date=data.earliest_start_date,
        parent_task_id=data.parent_task_id,
        task_type=data.task_type,
        flexible=not data.is_schedule_locked,
        metadata={"description": data.description or ""},
    )


def _is_vague(data: ScheduleItemInput) -> bool:
    if data.estimated_hours is not None:
        return False
    description = (data.description or "").strip()
    words = [word for word in data.title.strip().split() if word]
    return len(words) <= 3 and len(description) < 24


def preference_dict(row: Optional[SchedulingPreference], user_id: int) -> dict:
    values = dict(DEFAULT_PREFERENCES)
    if row:
        for key in values:
            values[key] = getattr(row, key)
    values["id"] = row.id if row else 0
    values["user_id"] = user_id
    values["version"] = row.version if row else 0
    for key in ("default_capacity_hours", "reserve_ratio", "balanced_target_ratio", "min_chunk_hours", "max_chunk_hours"):
        values[key] = float(values[key])
    return values


def get_preferences(db: Session, user_id: int) -> dict:
    row = db.query(SchedulingPreference).filter(SchedulingPreference.user_id == user_id).first()
    return preference_dict(row, user_id)


def update_preferences(db: Session, user_id: int, data: SchedulingPreferenceUpdate) -> dict:
    row = db.query(SchedulingPreference).filter(SchedulingPreference.user_id == user_id).first()
    if row and data.version is not None and row.version != data.version:
        raise ScheduleError("scheduling preferences are stale; reload and retry", code="stale_preferences")
    values = data.model_dump(exclude={"version"})
    if row is None:
        row = SchedulingPreference(user_id=user_id, **values, version=1)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.version = int(row.version or 1) + 1
    db.commit()
    db.refresh(row)
    return preference_dict(row, user_id)


def list_capacity_overrides(db: Session, user_id: int) -> list[dict]:
    rows = (
        db.query(ScheduleCapacityOverride)
        .filter(ScheduleCapacityOverride.user_id == user_id)
        .order_by(ScheduleCapacityOverride.local_date.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "local_date": row.local_date.isoformat(),
            "capacity_hours": float(row.capacity_hours),
            "note": row.note,
            "version": row.version,
        }
        for row in rows
    ]


def upsert_capacity_override(db: Session, user_id: int, data: CapacityOverrideUpsert) -> dict:
    row = (
        db.query(ScheduleCapacityOverride)
        .filter(
            ScheduleCapacityOverride.user_id == user_id,
            ScheduleCapacityOverride.local_date == data.local_date,
        )
        .first()
    )
    if row and data.version is not None and row.version != data.version:
        raise ScheduleError("capacity override is stale; reload and retry", code="stale_capacity")
    if row is None:
        row = ScheduleCapacityOverride(
            user_id=user_id,
            local_date=data.local_date,
            capacity_hours=data.capacity_hours,
            note=data.note,
            version=1,
        )
        db.add(row)
    else:
        row.capacity_hours = data.capacity_hours
        row.note = data.note
        row.version = int(row.version or 1) + 1
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "local_date": row.local_date.isoformat(),
        "capacity_hours": float(row.capacity_hours),
        "note": row.note,
        "version": row.version,
    }


def delete_capacity_override(db: Session, user_id: int, local_date: date) -> bool:
    row = (
        db.query(ScheduleCapacityOverride)
        .filter(
            ScheduleCapacityOverride.user_id == user_id,
            ScheduleCapacityOverride.local_date == local_date,
        )
        .first()
    )
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def _audit(
    db: Session,
    user_id: int,
    event_type: str,
    *,
    actor: str = "user",
    plan_id: Optional[int] = None,
    intervention_id: Optional[int] = None,
    affected_items: Optional[list] = None,
    reason_codes: Optional[list] = None,
    profile: Optional[str] = None,
    correlation_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> ScheduleAuditEvent:
    event = ScheduleAuditEvent(
        user_id=user_id,
        event_type=event_type,
        actor=actor,
        plan_id=plan_id,
        intervention_id=intervention_id,
        affected_items=sanitize_affected_items(affected_items),
        reason_codes=sanitize_reason_codes(reason_codes),
        algorithm_version=ALGORITHM_VERSION,
        profile=profile,
        metadata_json=sanitize_audit_metadata(metadata),
        correlation_id=correlation_id,
    )
    db.add(event)
    return event


def record_schedule_outcome(
    db: Session,
    user_id: int,
    source_type: str,
    source_id: int,
    completion_state: str,
    *,
    typed_capture_enabled: Optional[bool] = None,
) -> None:
    """Preserve legacy audit and append a consented typed completion event."""
    normalized_state = str(completion_state or "").lower()
    terminal_state = "completed" if normalized_state in {"done", "complete", "completed"} else "unknown"
    _audit(
        db,
        user_id,
        "schedule_outcome_observed",
        actor="user",
        affected_items=[{"source_type": source_type, "source_id": source_id}],
        reason_codes=["completion_outcome"],
        metadata={
            "source_type": source_type,
            "source_id": source_id,
            "completion_state": normalized_state,
            "outcome": terminal_state,
        },
    )
    db.commit()
    try:
        from schemas.schedule_personalization import OutcomeObservationInput
        from services.schedule_personalization_config import personalization_runtime_config
        from services.schedule_source_access import owned_schedule_source
        from services.schedule_work_events import record_outcome_observation

        source = owned_schedule_source(db, user_id, source_type, source_id)
        if source is None:
            return
        source_version = int(getattr(source, "schedule_version", 1) or 1)
        source_updated = getattr(source, "update_time", None) or getattr(source, "updated_at", None)
        update_token = source_updated.isoformat() if source_updated else "na"
        idempotency_key = f"legacy:{source_type}:{source_id}:{terminal_state}:{source_version}:{update_token}"[:128]
        enabled = (
            personalization_runtime_config.effective_capture_enabled
            if typed_capture_enabled is None
            else typed_capture_enabled
        )
        record_outcome_observation(
            db,
            user_id,
            OutcomeObservationInput(
                source={"source_type": source_type, "source_id": source_id},
                idempotency_key=idempotency_key,
                terminal_state=terminal_state,
                provenance="lifecycle",
                confidence="medium",
            ),
            capture_enabled=enabled,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "typed_schedule_outcome_capture_failed user_id=%s source_type=%s error_type=%s",
            user_id,
            source_type,
            type(exc).__name__,
        )


def _intervention_result(
    *,
    source_type: str,
    requested_date: date,
    projected_count: int,
    recommendation: Optional[RecommendationResult],
    intervention_id: Optional[int],
    state: str,
    correlation_id: str,
    clarification_question: Optional[str] = None,
    clarification_reason_code: Optional[str] = None,
    clarification_sensitivity: Optional[dict] = None,
    error_code: Optional[str] = None,
) -> dict:
    return {
        "kind": "overload_intervention" if recommendation else ("clarification" if clarification_question else "analysis_error"),
        "intervention_id": intervention_id,
        "state": state,
        "source_type": source_type,
        "requested_date": requested_date.isoformat(),
        "projected_count": projected_count,
        "complete_day": list(recommendation.complete_day if recommendation else ()),
        "recommendation": _serialize_candidate(recommendation.recommended if recommendation else None),
        "alternatives": [_serialize_candidate(candidate) for candidate in (recommendation.alternatives if recommendation else ())],
        "clarification_question": clarification_question,
        "clarification_reason_code": clarification_reason_code,
        "clarification_sensitivity": clarification_sensitivity,
        "error_code": error_code,
        "input_revision": None,
        "correlation_id": correlation_id,
    }


def preflight_creation(
    db: Session,
    user_id: int,
    data: ScheduleItemInput,
    *,
    persist_intervention: bool = True,
    override_allowed: bool = False,
    personalization_config=None,
) -> dict:
    correlation_id = getattr(data, "correlation_id", None) or uuid.uuid4().hex
    try:
        snapshot = load_snapshot(db, user_id)
    except Exception:
        db.rollback()
        return _intervention_result(
            source_type=data.source_type.value,
            requested_date=data.target_date,
            projected_count=0,
            recommendation=None,
            intervention_id=None,
            state="analysis_error",
            correlation_id=correlation_id,
            error_code="workload_read_failed",
        )
    effective_data = data
    proposed = _item_from_request(effective_data, user_id)
    count = len({item.key for item in snapshot.items_on(data.target_date)} | {proposed.key})

    if count <= INTERVENTION_THRESHOLD:
        return {
            "kind": "create",
            "state": "ready",
            "source_type": data.source_type.value,
            "requested_date": data.target_date.isoformat(),
            "projected_count": count,
            "input_revision": snapshot.revision,
            "correlation_id": correlation_id,
        }

    clarification = None
    if _is_vague(data):
        archetype = normalize_task_archetype(
            title=data.title,
            description=data.description,
            structured_kind=data.schedule_kind,
        )
        prior = resolve_effort_prior(
            task_archetype=archetype.task_archetype,
            subject=data.subject,
        )
        clarification = analyze_clarification_value(
            snapshot,
            proposed,
            data.target_date,
            assumptions_from_effort_prior(prior),
            unresolved_fields=("effort_hours",),
        )
        if clarification.should_ask:
            result = _intervention_result(
                source_type=data.source_type.value,
                requested_date=data.target_date,
                projected_count=count,
                recommendation=None,
                intervention_id=None,
                state="clarification_required",
                correlation_id=correlation_id,
                clarification_question=clarification.question,
                clarification_reason_code=clarification.reason_code,
                clarification_sensitivity=clarification.to_dict(),
                error_code="ambiguous_effort_material",
            )
            if persist_intervention:
                row = ScheduleIntervention(
                    user_id=user_id,
                    source_type=data.source_type.value,
                    provisional_payload=_as_json(data),
                    target_date=data.target_date,
                    input_revision=snapshot.revision,
                    projected_count=count,
                    ranked_recommendations=[],
                    state="clarification_required",
                    correlation_id=correlation_id,
                    expires_at=_now() + timedelta(minutes=30),
                )
                db.add(row)
                db.commit()
                result["intervention_id"] = row.id
                result["input_revision"] = snapshot.revision
            return result
        proposed = replace(
            proposed,
            estimated_hours=clarification.conservative_effort_hours,
            effort_source="versioned_product_prior_p90",
        )
        effective_data = data.model_copy(update={
            "estimated_hours": clarification.conservative_effort_hours,
            "effort_source": "versioned_product_prior_p90",
        })

    recommendation = recommend_date(snapshot, proposed, data.target_date, "balanced")
    if not recommendation.feasible:
        result = _intervention_result(
            source_type=data.source_type.value,
            requested_date=data.target_date,
            projected_count=count,
            recommendation=recommendation,
            intervention_id=None,
            state="analysis_error",
            correlation_id=correlation_id,
            clarification_reason_code=clarification.reason_code if clarification else None,
            clarification_sensitivity=clarification.to_dict() if clarification else None,
            error_code="infeasible_schedule",
        )
    else:
        result = _intervention_result(
            source_type=data.source_type.value,
            requested_date=data.target_date,
            projected_count=count,
            recommendation=recommendation,
            intervention_id=None,
            state="pending",
            correlation_id=correlation_id,
            clarification_reason_code=clarification.reason_code if clarification else None,
            clarification_sensitivity=clarification.to_dict() if clarification else None,
        )

    result["input_revision"] = snapshot.revision
    deterministic_ranked = (
        ([result["recommendation"]] if result.get("recommendation") else [])
        + result.get("alternatives", [])
    )
    try:
        from services.schedule_adaptive_integration import annotate_deterministic_recommendations
        from services.schedule_personalization_config import personalization_runtime_config

        result["personalization"] = annotate_deterministic_recommendations(
            db,
            user_id=user_id,
            recommendations=deterministic_ranked,
            context_identity=f"preflight:{correlation_id}:{snapshot.revision}",
            hard_deadline=effective_data.hard_deadline_date,
            config=personalization_config or personalization_runtime_config,
        )
        annotations_by_id = {
            item["candidate_id"]: item
            for item in result["personalization"].get("annotations", [])
        }
        display_rank = {
            candidate_id: rank
            for rank, candidate_id in enumerate(result["personalization"].get("display_order", []), start=1)
        }
        exploration = result["personalization"].get("exploration") or {}
        for rank, item in enumerate(deterministic_ranked, start=1):
            candidate_id = f"date:{item['date']}"
            annotation = annotations_by_id.get(candidate_id, {})
            item.update({
                "baseline_rank": rank,
                "personalized_rank": annotation.get("personalized_rank", rank),
                "learned_adjustment": annotation.get("learned_adjustment", 0),
                "display_rank": display_rank.get(candidate_id, rank),
                "model_version": result["personalization"].get("model_version"),
                "randomized_assignment": bool(exploration.get("randomized")),
                "assignment_probability": exploration.get("assignment_probability"),
                "assignment_denominator": exploration.get("assignment_denominator"),
            })
    except Exception as exc:
        logger.warning(
            "schedule_personalization_annotation_failed user_id=%s error_type=%s",
            user_id,
            type(exc).__name__,
        )
        result["personalization"] = {
            "serving_mode": "disabled",
            "baseline_order": [f"date:{item['date']}" for item in deterministic_ranked],
            "display_order": [f"date:{item['date']}" for item in deterministic_ranked],
            "fallback_reason": "integration_failure",
            "annotations": [],
            "authority": {
                "feasibility": "deterministic_scheduler",
                "apply_order": "deterministic_baseline",
                "learned_auto_apply": False,
            },
        }
    if persist_intervention:
        row = ScheduleIntervention(
            user_id=user_id,
            source_type=data.source_type.value,
            provisional_payload=_as_json(effective_data),
            target_date=data.target_date,
            input_revision=snapshot.revision,
            projected_count=count,
            ranked_recommendations=deterministic_ranked,
            state=result["state"],
            correlation_id=correlation_id,
            expires_at=_now() + timedelta(minutes=30),
        )
        db.add(row)
        db.flush()
        result["intervention_id"] = row.id
        _audit(
            db,
            user_id,
            "intervention_created",
            intervention_id=row.id,
            reason_codes=(result.get("recommendation") or {}).get("reason_codes", []),
            correlation_id=correlation_id,
            metadata={
                "projected_count": count,
                "state": result["state"],
                "feature_snapshot": {
                    "requested_date": data.target_date.isoformat(),
                    "projected_count": count,
                    "recommendation_energy_ratio": (result.get("recommendation") or {}).get("energy_ratio"),
                    "alternative_count": len(result.get("alternatives", [])),
                },
                "deterministic_rank": [
                    item.get("date")
                    for item in ([result["recommendation"]] if result.get("recommendation") else []) + result.get("alternatives", [])
                ],
            },
        )
        db.commit()
    return result


def _create_item(db: Session, user_id: int, data: ScheduleItemInput, target_date: date) -> dict:
    if data.source_type.value == "task":
        task = Task(
            user_id=user_id,
            id_name=data.title,
            task_type=TaskType(data.task_type),
            title=data.title,
            description=data.description or "",
            subject=data.subject,
            category=data.category,
            priority=data.priority,
            deadline=target_date,
            estimated_hours=float(data.estimated_hours or 0),
            status="todo" if data.status == "pending" else data.status,
            earliest_start_date=data.earliest_start_date,
            hard_deadline_date=data.hard_deadline_date,
            energy_intensity=data.energy_intensity,
            effort_source=data.effort_source,
            is_schedule_locked=data.is_schedule_locked,
            schedule_kind=data.schedule_kind,
        )
        db.add(task)
        db.flush()
        return {
            "ok": True,
            "source_type": "task",
            "id": task.id,
            "title": task.title,
            "date": target_date.isoformat(),
            "schedule_version": task.schedule_version,
        }

    if data.source_type.value == "deadline":
        deadline = Deadline(
            user_id=user_id,
            title=data.title,
            description=data.description or "",
            subject=data.subject,
            due_date=target_date,
            priority=data.priority,
            status="pending" if data.status == "todo" else data.status,
            estimated_hours=data.estimated_hours,
            energy_intensity=data.energy_intensity,
            effort_source=data.effort_source,
            is_schedule_locked=True,
            schedule_kind=data.schedule_kind,
        )
        db.add(deadline)
        db.flush()
        return {
            "ok": True,
            "source_type": "deadline",
            "id": deadline.id,
            "title": deadline.title,
            "date": target_date.isoformat(),
            "schedule_version": deadline.schedule_version,
        }

    parent = db.query(Task).filter(Task.id == data.parent_task_id, Task.user_id == user_id).first()
    if not parent:
        raise ScheduleError("parent task does not exist or is not accessible", 404, "parent_not_found")
    subtask = SubTask(
        task_id=parent.id,
        name=data.title,
        description=data.description or "",
        notice_time=target_date,
        level=data.priority,
        status="pending" if data.status == "todo" else data.status,
        estimated_hours=float(data.estimated_hours or 0),
        earliest_start_date=data.earliest_start_date,
        hard_deadline_date=data.hard_deadline_date,
        energy_intensity=data.energy_intensity,
        effort_source=data.effort_source,
        is_schedule_locked=data.is_schedule_locked,
        schedule_kind=data.schedule_kind,
    )
    db.add(subtask)
    db.flush()
    return {
        "ok": True,
        "source_type": "subtask",
        "id": subtask.id,
        "parent_task_id": parent.id,
        "title": subtask.name,
        "date": target_date.isoformat(),
        "schedule_version": subtask.schedule_version,
    }


def resolve_intervention(
    db: Session,
    user_id: int,
    intervention_id: int,
    data: InterventionResolveRequest,
) -> dict:
    row = (
        db.query(ScheduleIntervention)
        .filter(ScheduleIntervention.id == intervention_id, ScheduleIntervention.user_id == user_id)
        .first()
    )
    if not row:
        raise ScheduleError("intervention does not exist or is not accessible", 404, "intervention_not_found")
    if row.state in {"resolved", "expired"}:
        if row.resolution_idempotency_key == data.idempotency_key:
            return {"ok": True, "intervention_id": row.id, "state": row.state, "decision": row.decision}
        raise ScheduleError("intervention is no longer pending", code="intervention_closed")
    if row.expires_at < _now():
        row.state = "expired"
        db.commit()
        raise ScheduleError("intervention has expired; run preflight again", code="intervention_expired")

    payload = dict(row.provisional_payload or {})
    payload["source_type"] = row.source_type
    payload["target_date"] = row.target_date.isoformat()
    payload.pop("correlation_id", None)
    original = ScheduleItemInput.model_validate(payload)
    selected_date = row.target_date
    if data.decision == ScheduleDecision.accept_recommendation:
        recommendations = row.ranked_recommendations or []
        if not recommendations:
            raise ScheduleError("no recommendation is available", code="no_recommendation")
        selected_date = date.fromisoformat(recommendations[0]["date"])
    elif data.decision == ScheduleDecision.choose_date:
        selected_date = data.selected_date

    if data.decision == ScheduleDecision.keep_original:
        # Re-read current data before honoring the explicit override.  The
        # threshold remains advisory, but the choice is never based solely on
        # stale chat memory.
        preflight_creation(db, user_id, original, persist_intervention=False)
        result = _create_item(db, user_id, original, row.target_date)
    else:
        candidate = original.model_copy(update={"target_date": selected_date})
        fresh = preflight_creation(db, user_id, candidate, persist_intervention=True)
        if fresh.get("kind") != "create":
            return fresh
        result = _create_item(db, user_id, candidate, selected_date)

    row.state = "resolved"
    row.decision = data.decision.value
    row.selected_date = selected_date
    row.resolution_idempotency_key = data.idempotency_key
    row.resolved_at = _now()
    _audit(
        db,
        user_id,
        "intervention_resolved",
        intervention_id=row.id,
        affected_items=[{
            "source_type": row.source_type,
            "source_id": result.get("id"),
            "date": selected_date.isoformat(),
        }],
        reason_codes=[data.decision.value],
        correlation_id=row.correlation_id,
        metadata={
            "idempotency_key": data.idempotency_key[:8],
            "user_choice": data.decision.value,
            "override": data.decision == ScheduleDecision.keep_original,
            "selected_date": selected_date.isoformat(),
            "deterministic_rank": [
                item.get("date") for item in (row.ranked_recommendations or [])[:4]
            ],
        },
    )
    db.commit()
    try:
        from services.schedule_observation_hooks import capture_intervention_resolution_after_commit

        capture_intervention_resolution_after_commit(
            db,
            user_id,
            row,
            result["source_type"],
            result["id"],
            selected_date,
            data.decision.value,
        )
    except Exception:
        # The operational creation and resolution are already durable.
        db.rollback()
    try:
        # Late import avoids a lifecycle/trigger module cycle. The resolved
        # creation is already durable, so optional analysis is failure-isolated.
        from services.schedule_triggers import analyze_after_mutation
        analyze_after_mutation(db, user_id, "agent_intervention_resolved")
    except Exception:
        db.rollback()
    result["intervention_id"] = row.id
    result["decision"] = data.decision.value
    return result


def analyze(db: Session, user_id: int, start_date: Optional[date], end_date: Optional[date]) -> dict:
    from services.schedule_engine import analyze_dates

    snapshot = load_snapshot(db, user_id)
    rows, blockers = analyze_dates(snapshot, start_date, end_date)
    return {
        "input_revision": snapshot.revision,
        "algorithm_version": ALGORITHM_VERSION,
        "profile": "balanced",
        "dates": rows,
        "feasible": not blockers,
        "blockers": blockers,
    }


def _plan_dict(plan: SchedulePlan, items: Iterable[SchedulePlanItem]) -> dict:
    item_list = list(items)
    result = dict(plan.result_snapshot or {})
    result.update({
        "id": plan.id,
        "user_id": plan.user_id,
        "profile": plan.profile,
        "algorithm_version": plan.algorithm_version,
        "input_revision": plan.input_revision,
        "state": plan.state,
        "projected_loads": plan.projected_loads or [],
        "item_changes": [
            {
                "source_type": item.source_type,
                "source_id": item.source_id,
                "before_date": item.before_date.isoformat() if item.before_date else None,
                "after_date": item.after_date.isoformat() if item.after_date else None,
                "before_version": item.before_version,
                "after_version": item.after_version,
                "score": float(item.score),
                "reason_codes": item.reason_codes or [],
                "chunks": (item.after_values or {}).get("chunks", []),
            }
            for item in item_list
        ],
        "expires_at": plan.expires_at,
        "created_at": plan.created_at,
    })
    return result


def create_plan(db: Session, user_id: int, data: PlanCreateRequest) -> dict:
    profile_name = (data.profile.value if data.profile else "balanced")
    if data.idempotency_key:
        existing = (
            db.query(SchedulePlan)
            .filter(SchedulePlan.user_id == user_id, SchedulePlan.idempotency_key == data.idempotency_key)
            .first()
        )
        if existing:
            return _plan_dict(existing, db.query(SchedulePlanItem).filter(SchedulePlanItem.plan_id == existing.id).all())

    snapshot = load_snapshot(db, user_id)
    result = rebalance(snapshot, profile_name)
    profile_previews = {}
    for candidate_profile in ("conservative", "balanced", "sprint"):
        profile_result = rebalance(snapshot, candidate_profile)
        profile_previews[candidate_profile] = {
            "recommended": candidate_profile == profile_name,
            "feasible": profile_result.feasible,
            "placement_count": len(profile_result.placements),
            "blockers": list(profile_result.blockers),
            "capacity_deficit_hours": profile_result.capacity_deficit_hours,
            "earliest_feasible_completion_date": (
                profile_result.earliest_feasible_completion_date.isoformat()
                if profile_result.earliest_feasible_completion_date else None
            ),
            "affected_items": list(profile_result.affected_items),
            "daily_loads": list(profile_result.daily_loads),
        }
    plan = SchedulePlan(
        user_id=user_id,
        profile=profile_name,
        algorithm_version=ALGORITHM_VERSION,
        input_revision=snapshot.revision,
        config_snapshot={
            "profile": profile_name,
            "profiles": profile_previews,
            "capacity": snapshot.preferences.default_capacity_hours,
            "reserve_ratio": snapshot.preferences.reserve_ratio,
        },
        projected_loads=list(result.daily_loads),
        state="preview",
        idempotency_key=data.idempotency_key,
        result_snapshot={
            "feasible": result.feasible,
            "blockers": list(result.blockers),
            "capacity_deficit_hours": result.capacity_deficit_hours,
            "earliest_feasible_completion_date": (
                result.earliest_feasible_completion_date.isoformat()
                if result.earliest_feasible_completion_date else None
            ),
            "affected_items": list(result.affected_items),
            "profile_previews": profile_previews,
        },
        expires_at=_now() + timedelta(hours=2),
    )
    db.add(plan)
    db.flush()
    for placement in result.placements:
        existing_allocations = (
            db.query(ScheduleAllocation)
            .filter(
                ScheduleAllocation.user_id == user_id,
                ScheduleAllocation.source_type == placement.item_key.split(":", 1)[0],
                ScheduleAllocation.source_id == int(placement.item_key.split(":", 1)[1]),
                ScheduleAllocation.state == "active",
            )
            .order_by(ScheduleAllocation.id.asc())
            .all()
        )
        db.add(SchedulePlanItem(
            plan_id=plan.id,
            source_type=placement.item_key.split(":", 1)[0],
            source_id=int(placement.item_key.split(":", 1)[1]),
            before_date=placement.before_date,
            after_date=placement.after_date,
            before_version=placement.before_version,
            after_version=placement.before_version + 1,
            before_values={
                "date": placement.before_date.isoformat() if placement.before_date else None,
                "allocations": [
                    {
                        "id": allocation.id,
                        "date": allocation.local_date.isoformat(),
                        "effort_hours": float(allocation.effort_hours),
                        "energy_points": float(allocation.energy_points),
                        "version": int(allocation.version or 1),
                    }
                    for allocation in existing_allocations
                ],
            },
            after_values={
                "date": placement.after_date.isoformat() if placement.after_date else None,
                "chunks": [
                    {"date": chunk_date.isoformat(), "effort_hours": hours}
                    for chunk_date, hours in placement.chunks
                ],
            },
            effort_hours=placement.effort_hours,
            score=placement.score,
            reason_codes=list(placement.reason_codes),
        ))
    _audit(
        db,
        user_id,
        "plan_preview_created",
        plan_id=plan.id,
        affected_items=[placement.to_dict() for placement in result.placements],
        reason_codes=list(result.blockers),
        profile=profile_name,
        metadata={"feasible": result.feasible},
    )
    db.commit()
    db.refresh(plan)
    persisted_items = db.query(SchedulePlanItem).filter(SchedulePlanItem.plan_id == plan.id).all()
    try:
        from services.schedule_observation_hooks import capture_plan_preview_after_commit

        capture_plan_preview_after_commit(db, user_id, plan, persisted_items)
    except Exception:
        # Preview durability and deterministic output do not depend on analytics.
        db.rollback()
    return _plan_dict(plan, persisted_items)


def get_plan(db: Session, user_id: int, plan_id: int) -> dict:
    plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_id, SchedulePlan.user_id == user_id).first()
    if not plan:
        raise ScheduleError("plan does not exist or is not accessible", 404, "plan_not_found")
    return _plan_dict(plan, db.query(SchedulePlanItem).filter(SchedulePlanItem.plan_id == plan.id).all())


def _source_row(db: Session, user_id: int, source_type: str, source_id: int, lock: bool = False):
    query = None
    if source_type == "task":
        query = db.query(Task).filter(Task.id == source_id, Task.user_id == user_id)
    elif source_type == "subtask":
        query = db.query(SubTask).join(Task, SubTask.task_id == Task.id).filter(SubTask.id == source_id, Task.user_id == user_id)
    elif source_type == "deadline":
        query = db.query(Deadline).filter(Deadline.id == source_id, Deadline.user_id == user_id)
    if query is None:
        return None
    if lock:
        query = query.with_for_update()
    return query.first()


def _current_date(row, source_type: str) -> Optional[date]:
    if source_type == "task":
        value = row.deadline
    elif source_type == "subtask":
        value = row.notice_time
    else:
        value = row.due_date
    return value.date() if isinstance(value, datetime) else value


def _set_date(row, source_type: str, value: date):
    if source_type == "task":
        row.deadline = value
    elif source_type == "subtask":
        row.notice_time = value
    else:
        raise ScheduleError("deadlines are locked and cannot be moved by this plan", code="hard_deadline")


def apply_plan(db: Session, user_id: int, plan_id: int, data: PlanApplyRequest, *, actor: str = "user") -> dict:
    plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_id, SchedulePlan.user_id == user_id).with_for_update().first()
    if not plan:
        raise ScheduleError("plan does not exist or is not accessible", 404, "plan_not_found")
    prior_result = dict(plan.result_snapshot or {})
    if plan.state == "applied" and prior_result.get("apply_idempotency_key") == data.idempotency_key:
        return _plan_dict(plan, db.query(SchedulePlanItem).filter(SchedulePlanItem.plan_id == plan.id).all())
    if plan.state != "preview":
        raise ScheduleError("plan is not eligible for apply", code="plan_closed")
    snapshot = load_snapshot(db, user_id)
    if snapshot.revision != data.expected_input_revision or snapshot.revision != plan.input_revision:
        raise ScheduleError("plan is stale; replan before applying", code="stale_plan")
    if plan.expires_at < _now():
        raise ScheduleError("plan has expired; replan before applying", code="plan_expired")

    plan_items = db.query(SchedulePlanItem).filter(SchedulePlanItem.plan_id == plan.id).all()
    validated_rows = []
    for plan_item in plan_items:
        row = _source_row(db, user_id, plan_item.source_type, plan_item.source_id, lock=True)
        if not row:
            raise ScheduleError("a planned source no longer exists; replan", code="source_missing")
        current_version = int(getattr(row, "schedule_version", 1) or 1)
        current_date = _current_date(row, plan_item.source_type)
        if current_version != plan_item.before_version or current_date != plan_item.before_date:
            raise ScheduleError("a planned item changed; replan before applying", code="stale_item")
        if plan_item.source_type == "deadline":
            raise ScheduleError("deadlines are locked and cannot be moved by this plan", code="hard_deadline")
        validated_rows.append((plan_item, row, current_version))

    applied_items = []
    for plan_item, row, current_version in validated_rows:
        _set_date(row, plan_item.source_type, plan_item.after_date)
        row.schedule_version = current_version + 1
        chunks = (plan_item.after_values or {}).get("chunks", [])
        chunk_dates = {chunk.get("date") for chunk in chunks if chunk.get("date")}
        active_allocations = db.query(ScheduleAllocation).filter(
            ScheduleAllocation.user_id == user_id,
            ScheduleAllocation.source_type == plan_item.source_type,
            ScheduleAllocation.source_id == plan_item.source_id,
            ScheduleAllocation.state == "active",
        ).all()
        for allocation in active_allocations:
            allocation.state = "superseded"
            allocation.version = int(allocation.version or 1) + 1
        if len(chunk_dates) > 1:
            intensity = float(getattr(row, "energy_intensity", 1.0) or 1.0)
            for chunk in chunks:
                db.add(ScheduleAllocation(
                    user_id=user_id,
                    source_type=plan_item.source_type,
                    source_id=plan_item.source_id,
                    local_date=date.fromisoformat(chunk["date"]),
                    effort_hours=float(chunk["effort_hours"]),
                    energy_points=float(chunk["effort_hours"]) * intensity,
                    state="active",
                    source_plan_item_id=plan_item.id,
                ))
        plan_item.after_version = row.schedule_version
        applied_items.append({"source_type": plan_item.source_type, "source_id": plan_item.source_id})

    plan.state = "applied"
    plan.applied_at = _now()
    plan.result_snapshot = {
        **prior_result,
        "applied_items": applied_items,
        "apply_idempotency_key": data.idempotency_key,
    }
    _audit(
        db,
        user_id,
        "plan_auto_applied" if actor == "system" else "plan_applied",
        actor=actor,
        plan_id=plan.id,
        affected_items=applied_items,
        profile=plan.profile,
        metadata={"idempotency_key": data.idempotency_key[:8]},
    )
    db.commit()
    try:
        from services.schedule_observation_hooks import capture_plan_apply_after_commit

        capture_plan_apply_after_commit(db, user_id, plan, plan_items, actor=actor)
    except Exception:
        # Apply is already committed; observation failure is analytical only.
        db.rollback()
    return _plan_dict(plan, plan_items)


def undo_plan(db: Session, user_id: int, plan_id: int, idempotency_key: str) -> dict:
    plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_id, SchedulePlan.user_id == user_id).with_for_update().first()
    if not plan:
        raise ScheduleError("plan does not exist or is not accessible", 404, "plan_not_found")
    prior_result = dict(plan.result_snapshot or {})
    if plan.state == "undone" and prior_result.get("undo_idempotency_key") == idempotency_key:
        return _plan_dict(plan, db.query(SchedulePlanItem).filter(SchedulePlanItem.plan_id == plan.id).all())
    if plan.state == "undone":
        raise ScheduleError("plan was already undone with a different idempotency key", code="plan_closed")
    if plan.state != "applied":
        raise ScheduleError("only an applied plan can be undone", code="plan_not_applied")
    plan_items = db.query(SchedulePlanItem).filter(SchedulePlanItem.plan_id == plan.id).all()
    validated_rows = []
    for plan_item in plan_items:
        row = _source_row(db, user_id, plan_item.source_type, plan_item.source_id, lock=True)
        if not row:
            raise ScheduleError("an affected item no longer exists; undo is unsafe", code="undo_source_missing")
        current_version = int(getattr(row, "schedule_version", 1) or 1)
        if current_version != plan_item.after_version or _current_date(row, plan_item.source_type) != plan_item.after_date:
            raise ScheduleError("a later edit prevents safe undo; replan instead", code="undo_conflict")
        previous_allocations = (plan_item.before_values or {}).get("allocations", [])
        for previous in previous_allocations:
            allocation = db.query(ScheduleAllocation).filter(
                ScheduleAllocation.id == previous.get("id"),
                ScheduleAllocation.user_id == user_id,
                ScheduleAllocation.source_type == plan_item.source_type,
                ScheduleAllocation.source_id == plan_item.source_id,
            ).with_for_update().first()
            if not allocation:
                raise ScheduleError("a previous allocation is missing; undo is unsafe", code="undo_allocation_missing")
            expected_version = int(previous.get("version", 1)) + 1
            if allocation.state != "superseded" or int(allocation.version or 1) != expected_version:
                raise ScheduleError("a later allocation edit prevents safe undo", code="undo_allocation_conflict")
        validated_rows.append((plan_item, row, current_version, previous_allocations))

    for plan_item, row, current_version, previous_allocations in validated_rows:
        _set_date(row, plan_item.source_type, plan_item.before_date)
        row.schedule_version = current_version + 1
        created_allocations = db.query(ScheduleAllocation).filter(
            ScheduleAllocation.user_id == user_id,
            ScheduleAllocation.source_type == plan_item.source_type,
            ScheduleAllocation.source_id == plan_item.source_id,
            ScheduleAllocation.source_plan_item_id == plan_item.id,
            ScheduleAllocation.state == "active",
        ).all()
        for allocation in created_allocations:
            allocation.state = "superseded"
            allocation.version = int(allocation.version or 1) + 1
        previous_ids = {int(value["id"]) for value in previous_allocations}
        if previous_ids:
            restored = db.query(ScheduleAllocation).filter(
                ScheduleAllocation.user_id == user_id,
                ScheduleAllocation.id.in_(previous_ids),
            ).all()
            for allocation in restored:
                allocation.state = "active"
                allocation.version = int(allocation.version or 1) + 1

    plan.state = "undone"
    plan.undo_of_plan_id = plan.id
    plan.result_snapshot = {**prior_result, "undo_idempotency_key": idempotency_key}
    _audit(
        db,
        user_id,
        "plan_undone",
        plan_id=plan.id,
        affected_items=[{"source_type": item.source_type, "source_id": item.source_id} for item in plan_items],
        profile=plan.profile,
        metadata={"idempotency_key": idempotency_key[:8]},
    )
    db.commit()
    return _plan_dict(plan, plan_items)


def replan(db: Session, user_id: int, plan_id: int) -> dict:
    old = db.query(SchedulePlan).filter(SchedulePlan.id == plan_id, SchedulePlan.user_id == user_id).first()
    if not old:
        raise ScheduleError("plan does not exist or is not accessible", 404, "plan_not_found")
    if old.state == "preview":
        old.state = "superseded"
    db.commit()
    result = create_plan(db, user_id, PlanCreateRequest(profile=ScheduleProfile(old.profile)))
    new = db.query(SchedulePlan).filter(SchedulePlan.id == result["id"]).first()
    if new:
        new.supersedes_plan_id = old.id
        db.commit()
    return result


def history(db: Session, user_id: int, limit: int = 50, before_id: Optional[int] = None) -> list[dict]:
    query = db.query(ScheduleAuditEvent).filter(ScheduleAuditEvent.user_id == user_id)
    if before_id:
        query = query.filter(ScheduleAuditEvent.id < before_id)
    rows = query.order_by(ScheduleAuditEvent.id.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "event_type": row.event_type,
            "actor": row.actor,
            "plan_id": row.plan_id,
            "intervention_id": row.intervention_id,
            "affected_items": sanitize_affected_items(row.affected_items),
            "reason_codes": sanitize_reason_codes(row.reason_codes),
            "algorithm_version": row.algorithm_version,
            "profile": row.profile,
            "metadata_json": sanitize_audit_metadata(row.metadata_json),
            "correlation_id": row.correlation_id,
            "created_at": row.created_at,
        }
        for row in rows
    ]
