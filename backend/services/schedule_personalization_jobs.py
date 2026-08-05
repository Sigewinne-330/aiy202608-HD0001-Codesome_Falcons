"""Leased, idempotent background jobs for scheduling personalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from typing import Any, Callable, Mapping, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingGovernanceJob, SchedulingModelRegistry
from schemas.schedule_personalization import GovernanceJobStatus, GovernanceJobType
from services.schedule_aggregate_priors import materialize_aggregate_priors
from services.schedule_features import derive_sufficient_statistics
from services.schedule_labels import derive_outcome_label
from services.schedule_model_registry import register_candidate
from services.schedule_personalization_governance import get_or_create_private_consent, utc_now_naive
from services.schedule_personalization_config import load_personalization_runtime_config
from services.schedule_reflections import materialize_reflection_candidate


JOB_RUNNER_SCHEMA_VERSION = "scheduling-personalization-jobs.v1"
MAX_JOB_RESULT_BYTES = 32_768
JobHandler = Callable[[Session, SchedulingGovernanceJob], Mapping[str, Any]]


class GovernanceJobError(ValueError):
    pass


@dataclass(frozen=True)
class ClaimedGovernanceJob:
    job_id: str
    worker_id: str
    lease_expires_at: datetime
    attempt: int


@dataclass(frozen=True)
class JobExecutionResult:
    job_id: str
    status: str
    attempt: int
    retry_scheduled: bool
    result: dict[str, Any]
    error_code: Optional[str]


def _bounded_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GovernanceJobError("job result must be a mapping")
    try:
        encoded = json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GovernanceJobError("job result must be strict JSON") from exc
    if len(encoded) > MAX_JOB_RESULT_BYTES:
        raise GovernanceJobError("job result is oversized")
    return json.loads(encoded.decode("utf-8"))


def claim_governance_jobs(
    db: Session,
    *,
    worker_id: str,
    now: Optional[datetime] = None,
    limit: int = 10,
    lease_seconds: int = 120,
    job_types: Optional[set[str]] = None,
) -> tuple[ClaimedGovernanceJob, ...]:
    if not worker_id or len(worker_id) > 128:
        raise GovernanceJobError("worker_id is required and bounded")
    if not 1 <= limit <= 100 or not 5 <= lease_seconds <= 3_600:
        raise GovernanceJobError("claim bounds are invalid")
    current = now or utc_now_naive()
    eligible = or_(
        and_(
            SchedulingGovernanceJob.status == GovernanceJobStatus.pending.value,
            or_(SchedulingGovernanceJob.not_before.is_(None), SchedulingGovernanceJob.not_before <= current),
        ),
        and_(
            SchedulingGovernanceJob.status == GovernanceJobStatus.leased.value,
            SchedulingGovernanceJob.lease_expires_at <= current,
        ),
    )
    query = db.query(SchedulingGovernanceJob.id).filter(eligible)
    if job_types:
        query = query.filter(SchedulingGovernanceJob.job_type.in_(sorted(job_types)))
    candidate_ids = [row[0] for row in query.order_by(
        SchedulingGovernanceJob.not_before.asc(), SchedulingGovernanceJob.id.asc()
    ).limit(limit * 3).all()]
    claimed = []
    lease_until = current + timedelta(seconds=lease_seconds)
    for job_pk in candidate_ids:
        won = db.query(SchedulingGovernanceJob).filter(
            SchedulingGovernanceJob.id == job_pk,
            eligible,
        ).update({
            SchedulingGovernanceJob.status: GovernanceJobStatus.leased.value,
            SchedulingGovernanceJob.lease_owner: worker_id,
            SchedulingGovernanceJob.lease_expires_at: lease_until,
            SchedulingGovernanceJob.attempts: SchedulingGovernanceJob.attempts + 1,
            SchedulingGovernanceJob.last_error_code: None,
            SchedulingGovernanceJob.last_error_detail: None,
        }, synchronize_session=False)
        if won != 1:
            continue
        db.flush()
        row = db.query(SchedulingGovernanceJob).filter_by(id=job_pk).one()
        claimed.append(ClaimedGovernanceJob(row.job_id, worker_id, lease_until, int(row.attempts)))
        if len(claimed) >= limit:
            break
    return tuple(claimed)


def _still_owned(db: Session, claim: ClaimedGovernanceJob, now: datetime) -> SchedulingGovernanceJob:
    row = db.query(SchedulingGovernanceJob).filter_by(job_id=claim.job_id).with_for_update().one_or_none()
    if row is None:
        raise GovernanceJobError("job no longer exists")
    if (
        row.status != GovernanceJobStatus.leased.value
        or row.lease_owner != claim.worker_id
        or row.lease_expires_at is None
        or row.lease_expires_at < now
        or int(row.attempts) != claim.attempt
    ):
        raise GovernanceJobError("job lease is no longer owned")
    return row


def _promoted_identity(db: Session) -> set[tuple[int, str]]:
    return {
        (row.id, row.model_id)
        for row in db.query(SchedulingModelRegistry).filter_by(lifecycle="promoted").all()
    }


def execute_claimed_job(
    db: Session,
    claim: ClaimedGovernanceJob,
    *,
    handlers: Mapping[str, JobHandler],
    now: Optional[datetime] = None,
    maximum_attempts: int = 3,
    retry_delay_seconds: int = 60,
) -> JobExecutionResult:
    current = now or utc_now_naive()
    if not 1 <= maximum_attempts <= 20 or not 0 <= retry_delay_seconds <= 86_400:
        raise GovernanceJobError("retry policy is invalid")
    row = _still_owned(db, claim, current)
    handler = handlers.get(row.job_type)
    if handler is None:
        raise GovernanceJobError(f"no handler for job type {row.job_type}")
    promoted_before = _promoted_identity(db)
    try:
        with db.begin_nested():
            result = _bounded_mapping(handler(db, row))
            if row.job_type in {
                GovernanceJobType.update_model.value,
                GovernanceJobType.evaluate_model.value,
            } and _promoted_identity(db) != promoted_before:
                raise GovernanceJobError("training and evaluation jobs cannot self-promote")
            db.flush()
    except Exception as exc:
        db.expire_all()
        row = _still_owned(db, claim, current)
        terminal = int(row.attempts) >= maximum_attempts
        row.status = GovernanceJobStatus.failed.value if terminal else GovernanceJobStatus.pending.value
        row.not_before = None if terminal else current + timedelta(seconds=retry_delay_seconds)
        row.lease_owner = None
        row.lease_expires_at = None
        row.last_error_code = type(exc).__name__[:64]
        row.last_error_detail = str(exc)[:500]
        db.flush()
        return JobExecutionResult(
            job_id=row.job_id,
            status=row.status,
            attempt=int(row.attempts),
            retry_scheduled=not terminal,
            result={},
            error_code=row.last_error_code,
        )
    row = _still_owned(db, claim, current)
    row.status = GovernanceJobStatus.succeeded.value
    row.completed_at = current
    row.lease_owner = None
    row.lease_expires_at = None
    row.last_error_code = None
    row.last_error_detail = None
    row.payload_json = {**(row.payload_json or {}), "result": result, "runner_schema_version": JOB_RUNNER_SCHEMA_VERSION}
    db.flush()
    return JobExecutionResult(row.job_id, row.status, int(row.attempts), False, result, None)


def _require_user(job: SchedulingGovernanceJob) -> int:
    if job.user_id is None:
        raise GovernanceJobError("job requires a user owner")
    return int(job.user_id)


def _check_watermark(db: Session, job: SchedulingGovernanceJob) -> int:
    user_id = _require_user(job)
    consent = get_or_create_private_consent(db, user_id)
    expected = (job.payload_json or {}).get("eligibility_watermark")
    if expected is not None and int(expected) != int(consent.eligibility_watermark):
        raise GovernanceJobError("consent watermark changed during job")
    return user_id


def _derive_label_handler(db: Session, job: SchedulingGovernanceJob) -> Mapping[str, Any]:
    user_id = _check_watermark(db, job)
    payload = job.payload_json or {}
    cutoff = datetime.fromisoformat(payload["outcome_cutoff_at"])
    row = derive_outcome_label(
        db, user_id, payload["source_type"], int(payload["source_id"]), outcome_cutoff_at=cutoff
    )
    return {"label_id": row.id, "derivation_version": row.derivation_version}


def _refresh_features_handler(db: Session, job: SchedulingGovernanceJob) -> Mapping[str, Any]:
    user_id = _check_watermark(db, job)
    reference = date.fromisoformat((job.payload_json or {}).get("reference_date") or date.today().isoformat())
    rows = derive_sufficient_statistics(db, user_id, reference_date=reference)
    return {"snapshot_ids": [row.id for row in rows], "reference_date": reference.isoformat()}


def _update_model_handler(db: Session, job: SchedulingGovernanceJob) -> Mapping[str, Any]:
    user_id = _check_watermark(db, job)
    payload = job.payload_json or {}
    row = register_candidate(
        db,
        user_id=user_id,
        model_type=payload["model_type"],
        scope="personal",
        algorithm_version=payload["algorithm_version"],
        feature_schema_version=payload["feature_schema_version"],
        label_version=payload.get("label_version"),
        calibration_version=payload.get("calibration_version"),
        artifact_json=payload["artifact_json"],
        effective_sample_size=float(payload.get("effective_sample_size", 0)),
        source_eligibility_watermark=int(payload.get("eligibility_watermark", 1)),
        model_id=payload.get("model_id"),
    )
    return {"model_id": row.model_id, "lifecycle": row.lifecycle}


def _reflection_handler(db: Session, job: SchedulingGovernanceJob) -> Mapping[str, Any]:
    user_id = _check_watermark(db, job)
    payload = job.payload_json or {}
    result = materialize_reflection_candidate(
        db,
        user_id,
        payload.get("candidate"),
        generated_by_model=str(payload.get("generated_by_model") or ""),
        prompt_version=str(payload.get("prompt_version") or ""),
    )
    return {"status": result.status, "reason": result.reason, "memory_id": result.entry.memory_id if result.entry else None}


def _acknowledge_governance_handler(db: Session, job: SchedulingGovernanceJob) -> Mapping[str, Any]:
    user_id = _check_watermark(db, job) if job.user_id is not None else None
    return {"acknowledged": True, "user_id": user_id, "job_type": job.job_type}


def _recompute_aggregate_handler(
    db: Session, job: SchedulingGovernanceJob
) -> Mapping[str, Any]:
    """Rebuild an identifier-free snapshot after consent or deletion changes.

    The job payload may tighten the privacy threshold, but it cannot turn on a
    runtime-disabled aggregate pipeline.
    """
    payload = job.payload_json or {}
    reference = date.fromisoformat(payload.get("reference_date") or date.today().isoformat())
    try:
        minimum_contributors = int(payload.get("minimum_cell_contributors", 10))
    except (TypeError, ValueError) as exc:
        raise GovernanceJobError("minimum cell contributors must be an integer") from exc
    runtime = load_personalization_runtime_config()
    snapshot = materialize_aggregate_priors(
        db,
        reference_date=reference,
        enabled=runtime.effective_cross_user_enabled,
        minimum_cell_contributors=minimum_contributors,
    )
    result = snapshot.to_dict()
    result["trigger_user_id"] = _require_user(job) if job.user_id is not None else None
    result["runtime_enabled"] = runtime.effective_cross_user_enabled
    return result


DEFAULT_JOB_HANDLERS: dict[str, JobHandler] = {
    GovernanceJobType.derive_labels.value: _derive_label_handler,
    GovernanceJobType.refresh_features.value: _refresh_features_handler,
    GovernanceJobType.update_model.value: _update_model_handler,
    GovernanceJobType.evaluate_model.value: _acknowledge_governance_handler,
    GovernanceJobType.materialize_reflection.value: _reflection_handler,
    GovernanceJobType.enforce_retention.value: _acknowledge_governance_handler,
    GovernanceJobType.propagate_deletion.value: _acknowledge_governance_handler,
    GovernanceJobType.detect_drift.value: _acknowledge_governance_handler,
    GovernanceJobType.recompute_aggregate.value: _recompute_aggregate_handler,
}
