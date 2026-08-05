"""Non-sensitive readiness, incident audit, and runtime recovery controls."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingGovernanceJob, SchedulingModelRegistry
from services.schedule_model_registry import RegistryCompatibility, RegistryResolution, kill_model
from services.schedule_personalization_config import PersonalizationRuntimeConfig
from services.schedule_personalization_governance import utc_now_naive


OPERATIONS_SCHEMA_VERSION = "scheduling-personalization-operations.v1"
RUNTIME_CONTROL_JOB_TYPE = "runtime_control"
MODEL_INCIDENT_JOB_TYPE = "model_incident"


class PersonalizationOperationsError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeControlResult:
    active: bool
    event_id: str
    repeated: bool


def _latest_global_control(db: Session) -> Optional[SchedulingGovernanceJob]:
    return db.query(SchedulingGovernanceJob).filter(
        SchedulingGovernanceJob.job_type == RUNTIME_CONTROL_JOB_TYPE,
        SchedulingGovernanceJob.status == "succeeded",
    ).order_by(SchedulingGovernanceJob.id.desc()).first()


def global_kill_active(db: Session) -> bool:
    row = _latest_global_control(db)
    return bool(row and (row.payload_json or {}).get("global_kill_active"))


def effective_operational_config(db: Session, config: PersonalizationRuntimeConfig) -> PersonalizationRuntimeConfig:
    return replace(config, kill_switch=bool(config.kill_switch or global_kill_active(db)))


def set_global_kill(
    db: Session,
    *,
    active: bool,
    reason: str,
    actor: str,
    idempotency_key: str,
) -> RuntimeControlResult:
    if not reason or len(reason) > 255:
        raise PersonalizationOperationsError("reason is required and bounded")
    if not actor or len(actor) > 64:
        raise PersonalizationOperationsError("actor is required and bounded")
    if not idempotency_key or len(idempotency_key) > 128:
        raise PersonalizationOperationsError("idempotency_key is required and bounded")
    stable_key = f"runtime-control:{idempotency_key}"
    existing = db.query(SchedulingGovernanceJob).filter_by(idempotency_key=stable_key).one_or_none()
    if existing is not None:
        payload = existing.payload_json or {}
        if bool(payload.get("global_kill_active")) != bool(active):
            raise PersonalizationOperationsError("idempotency key was reused with a different state")
        return RuntimeControlResult(bool(active), existing.job_id, True)
    now = utc_now_naive()
    row = SchedulingGovernanceJob(
        job_id=str(uuid4()),
        idempotency_key=stable_key,
        user_id=None,
        job_type=RUNTIME_CONTROL_JOB_TYPE,
        status="succeeded",
        payload_json={
            "schema_version": OPERATIONS_SCHEMA_VERSION,
            "global_kill_active": bool(active),
            "reason": reason,
            "actor": actor,
            "deterministic_scheduling_available": True,
        },
        attempts=1,
        completed_at=now,
    )
    db.add(row)
    db.flush()
    return RuntimeControlResult(bool(active), row.job_id, False)


def kill_model_with_incident(
    db: Session,
    model_id: str,
    *,
    reason: str,
    actor: str,
    idempotency_key: str,
    compatibility: RegistryCompatibility,
) -> RegistryResolution:
    stable_key = f"model-incident:{idempotency_key}"
    existing = db.query(SchedulingGovernanceJob).filter_by(idempotency_key=stable_key).one_or_none()
    if existing is not None:
        payload = existing.payload_json or {}
        fallback_id = payload.get("fallback_model_id")
        fallback = db.query(SchedulingModelRegistry).filter_by(model_id=fallback_id).one_or_none() if fallback_id else None
        return RegistryResolution(fallback, payload.get("fallback_reason"))
    resolution = kill_model(db, model_id, reason=reason, compatibility=compatibility)
    now = utc_now_naive()
    db.add(SchedulingGovernanceJob(
        job_id=str(uuid4()),
        idempotency_key=stable_key,
        user_id=None,
        job_type=MODEL_INCIDENT_JOB_TYPE,
        status="succeeded",
        payload_json={
            "schema_version": OPERATIONS_SCHEMA_VERSION,
            "model_id": model_id,
            "reason": reason[:255],
            "actor": actor[:64],
            "fallback_model_id": resolution.model.model_id if resolution.model else None,
            "fallback_reason": resolution.fallback_reason,
            "deterministic_scheduling_available": True,
        },
        attempts=1,
        completed_at=now,
    ))
    db.flush()
    return resolution


def serving_version_history(
    db: Session,
    *,
    user_id: Optional[int] = None,
    model_type: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    query = db.query(SchedulingModelRegistry)
    if user_id is not None:
        query = query.filter(SchedulingModelRegistry.user_id == user_id)
    if model_type is not None:
        query = query.filter(SchedulingModelRegistry.model_type == model_type)
    rows = query.order_by(SchedulingModelRegistry.id.desc()).limit(max(1, min(limit, 200))).all()
    return [{
        "model_id": row.model_id,
        "model_type": row.model_type,
        "scope": row.scope,
        "lifecycle": row.lifecycle,
        "algorithm_version": row.algorithm_version,
        "feature_schema_version": row.feature_schema_version,
        "label_version": row.label_version,
        "calibration_version": row.calibration_version,
        "effective_sample_size": float(row.effective_sample_size or 0),
        "serving_started_at": row.serving_started_at,
        "serving_ended_at": row.serving_ended_at,
        "lifecycle_reason": row.lifecycle_reason,
        "created_at": row.created_at,
    } for row in rows]


def personalization_readiness(db: Session, config: PersonalizationRuntimeConfig) -> dict:
    effective = effective_operational_config(db, config)
    promoted = db.query(SchedulingModelRegistry).filter(
        SchedulingModelRegistry.lifecycle == "promoted",
        SchedulingModelRegistry.invalidated_at.is_(None),
    ).count()
    failed_jobs = db.query(SchedulingGovernanceJob).filter_by(status="failed").count()
    active_leases = db.query(SchedulingGovernanceJob).filter_by(status="leased").count()
    latest_monitoring = db.query(SchedulingGovernanceJob).filter_by(
        job_type="monitoring_snapshot", status="succeeded"
    ).order_by(SchedulingGovernanceJob.id.desc()).first()
    monitoring_payload = (latest_monitoring.payload_json or {}) if latest_monitoring else {}
    firing_alerts = [
        item for item in monitoring_payload.get("alerts", [])
        if item.get("status") == "firing"
    ]
    return {
        "schema_version": OPERATIONS_SCHEMA_VERSION,
        "ready": True,
        "deterministic_scheduling_available": True,
        "personalization_serving_mode": effective.effective_serving_mode.value,
        "global_kill_active": effective.kill_switch,
        "promoted_model_count": promoted,
        "failed_job_count": failed_jobs,
        "active_job_lease_count": active_leases,
        "monitoring_state": "unknown" if latest_monitoring is None else (
            "critical" if any(item.get("severity") == "critical" for item in firing_alerts)
            else "warning" if firing_alerts else "healthy"
        ),
        "firing_alert_count": len(firing_alerts),
        "contains_model_parameters": False,
        "contains_user_data": False,
    }
