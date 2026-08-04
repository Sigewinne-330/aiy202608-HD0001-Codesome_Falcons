"""Backend-first scheduling APIs; frontend screens arrive in a later change."""

from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models.app_user import AppUser as User
from schemas.scheduling import (
    AnalysisRequest,
    CapacityOverrideResponse,
    CapacityOverrideUpsert,
    InterventionResolveRequest,
    InterventionResponse,
    PlanApplyRequest,
    PlanCreateRequest,
    PlanResponse,
    PlanUndoRequest,
    PreflightRequest,
    SchedulingPreferenceResponse,
    SchedulingPreferenceUpdate,
)
from services.auth import get_current_user
from services.schedule_lifecycle import (
    ScheduleError,
    analyze,
    apply_plan,
    create_plan,
    delete_capacity_override,
    get_plan,
    get_preferences,
    history,
    list_capacity_overrides,
    preflight_creation,
    replan,
    resolve_intervention,
    undo_plan,
    update_preferences,
    upsert_capacity_override,
)
from services.schedule_policy import scheduling_enabled


router = APIRouter(prefix="/api/scheduling", tags=["scheduling"])


def _enabled():
    if not scheduling_enabled():
        raise HTTPException(status_code=404, detail="scheduling balancer is disabled")


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ScheduleError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail}) from exc


@router.get("/preferences", response_model=SchedulingPreferenceResponse)
def read_preferences(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _enabled()
    return get_preferences(db, current_user.id)


@router.put("/preferences", response_model=SchedulingPreferenceResponse)
def write_preferences(
    data: SchedulingPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(update_preferences, db, current_user.id, data)


@router.get("/capacity-overrides", response_model=List[CapacityOverrideResponse])
def read_capacity_overrides(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _enabled()
    return list_capacity_overrides(db, current_user.id)


@router.put("/capacity-overrides", response_model=CapacityOverrideResponse)
def write_capacity_override(
    data: CapacityOverrideUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(upsert_capacity_override, db, current_user.id, data)


@router.delete("/capacity-overrides/{local_date}")
def remove_capacity_override(
    local_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    removed = delete_capacity_override(db, current_user.id, local_date)
    if not removed:
        raise HTTPException(status_code=404, detail="capacity override not found")
    return {"ok": True, "local_date": local_date.isoformat()}


@router.post("/analyze")
def analyze_schedule(
    data: AnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return analyze(db, current_user.id, data.start_date, data.end_date)


@router.post("/interventions/preflight", response_model=InterventionResponse)
def preflight(
    data: PreflightRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(preflight_creation, db, current_user.id, data)


@router.post("/interventions/{intervention_id}/resolve")
def resolve(
    intervention_id: int,
    data: InterventionResolveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(resolve_intervention, db, current_user.id, intervention_id, data)


@router.post("/plans")
def create_schedule_plan(
    data: PlanCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(create_plan, db, current_user.id, data)


@router.get("/plans/{plan_id}")
def read_schedule_plan(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(get_plan, db, current_user.id, plan_id)


@router.post("/plans/{plan_id}/apply")
def apply_schedule_plan(
    plan_id: int,
    data: PlanApplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(apply_plan, db, current_user.id, plan_id, data)


@router.post("/plans/{plan_id}/undo")
def undo_schedule_plan(
    plan_id: int,
    data: PlanUndoRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(undo_plan, db, current_user.id, plan_id, data.idempotency_key)


@router.post("/plans/{plan_id}/replan")
def replan_schedule(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _call(replan, db, current_user.id, plan_id)


@router.get("/history")
def read_schedule_history(
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return {"items": history(db, current_user.id, limit=limit, before_id=before_id)}
