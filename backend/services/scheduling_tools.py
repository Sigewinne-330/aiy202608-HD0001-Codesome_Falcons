"""High-level Agent scheduling tools and dated-create guard."""

from __future__ import annotations

from datetime import date
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from schemas.scheduling import (
    AnalysisRequest,
    InterventionResolveRequest,
    PlanApplyRequest,
    PlanCreateRequest,
    PreflightRequest,
    ScheduleDecision,
    ScheduleItemInput,
    ScheduleProfile,
)
from services import task_tools
from services.schedule_lifecycle import (
    _create_item,
    analyze,
    apply_plan,
    create_plan,
    get_plan,
    history,
    preflight_creation,
    replan,
    resolve_intervention,
    undo_plan,
)
from services.schedule_policy import scheduling_enabled
from services.schedule_triggers import analyze_after_mutation


logger = logging.getLogger(__name__)


def _schedule_after_agent_create(db: Session, user_id: int, trigger: str) -> None:
    """Keep a committed Agent create successful if optional analysis fails."""
    try:
        analyze_after_mutation(db, user_id, trigger)
    except Exception:
        db.rollback()
        logger.exception("Schedule analysis failed after %s", trigger)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def create_task_with_preflight(
    db: Session,
    user_id: int,
    title: str,
    description: str = "",
    subject: str = "",
    category: str = "",
    deadline: Optional[str] = None,
    priority: str = "medium",
    estimated_hours: float = 0,
    task_type: str = "todo",
    status: str = "todo",
    personal_deadline: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Compatibility wrapper; the flag controls whether dated creation gates."""
    target_date = _parse_date(deadline)
    if not scheduling_enabled() or target_date is None:
        return task_tools.create_task(
            db=db,
            user_id=user_id,
            title=title,
            description=description,
            subject=subject,
            category=category,
            deadline=deadline,
            priority=priority,
            estimated_hours=estimated_hours,
            task_type=task_type,
            status=status,
            personal_deadline=personal_deadline,
        )

    data = PreflightRequest(
        source_type="task",
        title=title,
        description=description,
        subject=subject or None,
        category=category.upper() if category else None,
        target_date=target_date,
        estimated_hours=estimated_hours if estimated_hours > 0 else None,
        priority=priority,
        task_type=task_type,
        status=status,
        hard_deadline_date=_parse_date(personal_deadline),
        schedule_kind=category or None,
    )
    result = preflight_creation(db, user_id, data)
    if result.get("kind") != "create":
        return result
    created = _create_item(db, user_id, data, target_date)
    db.commit()
    _schedule_after_agent_create(db, user_id, "agent_task_create")
    return created


def create_subtask_with_preflight(
    db: Session,
    user_id: int,
    task_id: int,
    name: str,
    description: str = "",
    notice_time: Optional[str] = None,
    level: str = "medium",
    status: str = "todo",
    estimated_hours: Optional[float] = None,
    **kwargs,
) -> Dict[str, Any]:
    target_date = _parse_date(notice_time)
    if not scheduling_enabled() or target_date is None:
        return task_tools.create_subtask(
            db=db,
            user_id=user_id,
            task_id=task_id,
            name=name,
            description=description,
            notice_time=notice_time,
            level=level,
            status=status,
        )

    data = PreflightRequest(
        source_type="subtask",
        title=name,
        description=description,
        target_date=target_date,
        parent_task_id=task_id,
        estimated_hours=estimated_hours,
        priority=level,
        status=status,
    )
    result = preflight_creation(db, user_id, data)
    if result.get("kind") != "create":
        return result
    created = _create_item(db, user_id, data, target_date)
    db.commit()
    _schedule_after_agent_create(db, user_id, "agent_subtask_create")
    return created


def preflight_create_calendar_item(db: Session, user_id: int, **kwargs) -> dict:
    return preflight_creation(db, user_id, PreflightRequest.model_validate(kwargs))


def resolve_overload_intervention(db: Session, user_id: int, intervention_id: int, **kwargs) -> dict:
    return resolve_intervention(
        db,
        user_id,
        intervention_id,
        InterventionResolveRequest.model_validate(kwargs),
    )


def analyze_schedule(db: Session, user_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, **kwargs) -> dict:
    return analyze(db, user_id, _parse_date(start_date), _parse_date(end_date))


def create_schedule_plan(db: Session, user_id: int, profile: str = "balanced", idempotency_key: Optional[str] = None, **kwargs) -> dict:
    return create_plan(
        db,
        user_id,
        PlanCreateRequest(profile=ScheduleProfile(profile), idempotency_key=idempotency_key),
    )


def apply_schedule_plan(db: Session, user_id: int, plan_id: int, expected_input_revision: str, idempotency_key: str, **kwargs) -> dict:
    return apply_plan(
        db,
        user_id,
        plan_id,
        PlanApplyRequest(expected_input_revision=expected_input_revision, idempotency_key=idempotency_key),
    )


def undo_schedule_plan(db: Session, user_id: int, plan_id: int, idempotency_key: str, **kwargs) -> dict:
    return undo_plan(db, user_id, plan_id, idempotency_key)


def replan_schedule(db: Session, user_id: int, plan_id: int, **kwargs) -> dict:
    return replan(db, user_id, plan_id)


def get_schedule_log(db: Session, user_id: int, limit: int = 50, before_id: Optional[int] = None, **kwargs) -> list:
    return history(db, user_id, limit=limit, before_id=before_id)
