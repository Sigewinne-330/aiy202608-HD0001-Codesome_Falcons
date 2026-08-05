"""Authenticated work-evidence APIs for adaptive scheduling."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models.app_user import AppUser as User
from models.schedule_personalization import SchedulingWorkSession
from schemas.schedule_personalization import (
    ConsentSettingsUpdate,
    GlobalKillRequest,
    MemoryEntryUpdate,
    MemoryStatus,
    MemoryTier,
    ModelKillRequest,
    PersonalizationResetRequest,
    OutcomeObservationInput,
    WorkEventInput,
    WorkSessionStartRequest,
    WorkSessionStopRequest,
    WorkSessionTransitionRequest,
)
from services.auth import get_current_admin, get_current_user
from services.schedule_personalization_config import personalization_runtime_config
from services.schedule_consent import (
    ConsentSettingsError,
    ConsentVersionConflict,
    consent_settings_payload,
    update_consent_settings,
)
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_memory import (
    MemoryEditConflict,
    MemoryError,
    MemoryNotFound,
    delete_owned_memory,
    edit_explicit_memory,
    get_owned_memory,
    list_memory_entries,
    memory_entry_payload,
)
from services.schedule_data_controls import (
    deletion_status,
    portable_personalization_export,
    reset_personalization_model,
)
from services.schedule_policy import scheduling_enabled
from services.schedule_work_events import (
    WorkEventConflict,
    WorkEventError,
    WorkEventNotFound,
    WorkEventRateLimited,
    apply_work_event,
    reconcile_work_session,
    record_outcome_observation,
)
from services.schedule_model_registry import RegistryCompatibility
from services.schedule_personalization_operations import (
    kill_model_with_incident,
    personalization_readiness,
    serving_version_history,
    set_global_kill,
)
from services.schedule_personalization_dashboard import personalization_dashboard


router = APIRouter(prefix="/api/scheduling", tags=["scheduling-personalization"])


def _enabled() -> None:
    if not scheduling_enabled():
        raise HTTPException(status_code=404, detail="scheduling balancer is disabled")


def _session_payload(row: SchedulingWorkSession) -> dict:
    return {
        "id": row.public_id,
        "source": {"source_type": row.source_type, "source_id": row.source_id},
        "state": row.state,
        "timezone": row.timezone,
        "started_at": row.started_at,
        "paused_at": row.paused_at,
        "ended_at": row.ended_at,
        "accumulated_active_seconds": int(row.accumulated_active_seconds or 0),
        "version": int(row.version or 1),
    }


def _result_payload(result) -> dict:
    return {
        "status": "accepted" if result.event is not None else "excluded",
        "created": result.created,
        "excluded_reason": result.skipped_reason,
        "event_id": result.event.event_id if result.event else None,
        "event_type": result.event.event_type if result.event else None,
        "session": _session_payload(result.session) if result.session else None,
    }


def _owned_session(db: Session, user_id: int, public_id: str) -> SchedulingWorkSession:
    row = db.query(SchedulingWorkSession).filter_by(public_id=public_id, user_id=user_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "work_session_not_found"})
    return row


def _execute(db: Session, function, *args, **kwargs):
    try:
        result = function(*args, **kwargs)
        db.commit()
        return _result_payload(result)
    except WorkEventNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail={"code": "work_event_not_found"}) from exc
    except WorkEventRateLimited as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail={"code": "work_event_rate_limited"}) from exc
    except WorkEventConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "work_event_conflict", "message": str(exc)}) from exc
    except WorkEventError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "work_event_invalid", "message": str(exc)}) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail={"code": "work_event_unavailable"}) from exc


@router.get("/personalization/settings")
def read_personalization_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    row = get_or_create_private_consent(db, current_user.id)
    db.commit()
    return consent_settings_payload(row, personalization_runtime_config)


@router.put("/personalization/settings")
def write_personalization_settings(
    data: ConsentSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    try:
        row = update_consent_settings(db, current_user.id, data)
        db.commit()
        return consent_settings_payload(row, personalization_runtime_config)
    except ConsentVersionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "consent_version_conflict"}) from exc
    except ConsentSettingsError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "consent_settings_invalid", "message": str(exc)}) from exc


@router.get("/memory")
def read_memory_list(
    tier: MemoryTier | None = Query(default=None),
    source: str | None = Query(default=None, pattern="^(user|llm|session)$"),
    status: MemoryStatus | None = Query(default=MemoryStatus.current),
    search: str | None = Query(default=None, max_length=100),
    before: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    try:
        rows, next_cursor = list_memory_entries(
            db,
            current_user.id,
            tier=tier.value if tier else None,
            source=source,
            status=status.value if status else None,
            search=search,
            before_memory_id=before,
            limit=limit,
        )
        return {
            "items": [memory_entry_payload(db, row) for row in rows],
            "next_cursor": next_cursor,
        }
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "memory_not_found"}) from exc


@router.get("/memory/export")
def export_memory(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return portable_personalization_export(db, current_user.id)


@router.get("/memory/{memory_id}")
def read_memory_detail(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    try:
        return memory_entry_payload(
            db,
            get_owned_memory(db, current_user.id, memory_id),
            include_evidence=True,
        )
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "memory_not_found"}) from exc


@router.put("/memory/{memory_id}")
def update_memory_detail(
    memory_id: str,
    data: MemoryEntryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    try:
        row = edit_explicit_memory(db, current_user.id, memory_id, data)
        db.commit()
        return memory_entry_payload(db, row, include_evidence=True)
    except MemoryNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail={"code": "memory_not_found"}) from exc
    except MemoryEditConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "memory_not_editable"}) from exc
    except MemoryError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "memory_invalid", "message": str(exc)}) from exc


@router.delete("/memory/{memory_id}")
def remove_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    try:
        row = delete_owned_memory(db, current_user.id, memory_id)
        db.commit()
        return memory_entry_payload(db, row, include_evidence=True)
    except MemoryNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail={"code": "memory_not_found"}) from exc


@router.post("/personalization/reset")
def reset_personalization(
    data: PersonalizationResetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    try:
        job = reset_personalization_model(db, current_user.id, data)
        db.commit()
        return {
            "status": job.status,
            "rebuild_from_retained_evidence": bool(
                (job.payload_json or {}).get("rebuild_from_retained_evidence")
            ),
            "raw_evidence_preserved": True,
            "deterministic_scheduling_available": True,
        }
    except ConsentVersionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "consent_version_conflict"}) from exc


@router.get("/personalization/deletion-status")
def read_deletion_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return deletion_status(db, current_user.id)


@router.post("/work-sessions/start")
def start_work_session(
    data: WorkSessionStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    event = WorkEventInput(
        event_type="started",
        source=data.source,
        idempotency_key=data.idempotency_key,
        after_values={"timezone": data.timezone},
        provenance="active_timer",
        confidence="high",
    )
    return _execute(
        db,
        apply_work_event,
        db,
        current_user.id,
        event,
        capture_enabled=personalization_runtime_config.effective_capture_enabled,
    )


def _transition(
    db: Session,
    user_id: int,
    public_id: str,
    event_type: str,
    idempotency_key: str,
):
    session = _owned_session(db, user_id, public_id)
    event = WorkEventInput(
        event_type=event_type,
        source={"source_type": session.source_type, "source_id": session.source_id},
        idempotency_key=idempotency_key,
        provenance="active_timer",
        confidence="high",
    )
    return _execute(
        db,
        apply_work_event,
        db,
        user_id,
        event,
        session_public_id=public_id,
        capture_enabled=personalization_runtime_config.effective_capture_enabled,
    )


@router.post("/work-sessions/{public_id}/pause")
def pause_work_session(
    public_id: str,
    data: WorkSessionTransitionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _transition(db, current_user.id, public_id, "paused", data.idempotency_key)


@router.post("/work-sessions/{public_id}/resume")
def resume_work_session(
    public_id: str,
    data: WorkSessionTransitionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _transition(db, current_user.id, public_id, "resumed", data.idempotency_key)


@router.post("/work-sessions/{public_id}/stop")
def stop_work_session(
    public_id: str,
    data: WorkSessionStopRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    if data.reconciliation_action:
        _owned_session(db, current_user.id, public_id)
        return _execute(
            db,
            reconcile_work_session,
            db,
            current_user.id,
            public_id,
            effective_at=data.effective_at,
            idempotency_key=data.idempotency_key,
            action=data.reconciliation_action,
            server_now=datetime.now(timezone.utc),
            capture_enabled=personalization_runtime_config.effective_capture_enabled,
        )
    return _transition(db, current_user.id, public_id, "stopped", data.idempotency_key)


@router.get("/work-sessions/active")
def active_work_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    rows = db.query(SchedulingWorkSession).filter(
        SchedulingWorkSession.user_id == current_user.id,
        SchedulingWorkSession.state.in_(["active", "paused"]),
    ).order_by(SchedulingWorkSession.updated_at.desc(), SchedulingWorkSession.id.desc()).limit(100).all()
    return {"items": [_session_payload(row) for row in rows]}


@router.post("/outcomes")
def record_outcome(
    data: OutcomeObservationInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return _execute(
        db,
        record_outcome_observation,
        db,
        current_user.id,
        data,
        capture_enabled=personalization_runtime_config.effective_capture_enabled,
    )


@router.get("/personalization/operations/readiness")
def read_personalization_readiness(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return personalization_readiness(db, personalization_runtime_config)


@router.get("/personalization/operations/model-history")
def read_model_history(
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    return {"items": serving_version_history(db, user_id=current_user.id, limit=limit)}


@router.get("/personalization/dashboard")
def read_personalization_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _enabled()
    payload = personalization_dashboard(
        db, current_user.id, personalization_runtime_config
    )
    db.commit()
    return payload


@router.post("/admin/personalization/global-kill")
def write_global_kill(
    data: GlobalKillRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _enabled()
    result = set_global_kill(
        db,
        active=data.active,
        reason=data.reason,
        actor=f"admin:{admin.id}",
        idempotency_key=data.idempotency_key,
    )
    db.commit()
    return {
        "active": result.active,
        "event_id": result.event_id,
        "repeated": result.repeated,
        "deterministic_scheduling_available": True,
    }


@router.post("/admin/personalization/models/{model_id}/kill")
def write_model_kill(
    model_id: str,
    data: ModelKillRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _enabled()
    result = kill_model_with_incident(
        db,
        model_id,
        reason=data.reason,
        actor=f"admin:{admin.id}",
        idempotency_key=data.idempotency_key,
        compatibility=RegistryCompatibility(
            data.algorithm_version,
            data.feature_schema_version,
            data.label_version,
            data.calibration_version,
        ),
    )
    db.commit()
    return {
        "killed_model_id": model_id,
        "fallback_model_id": result.model.model_id if result.model else None,
        "fallback_reason": result.fallback_reason,
        "deterministic_scheduling_available": True,
    }
