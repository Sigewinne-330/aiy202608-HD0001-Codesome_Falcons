"""Conservative monitoring and recovery metadata for learned scheduling influence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math
from typing import Any, Mapping, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingGovernanceJob
from services.schedule_personalization_governance import utc_now_naive
from services.schedule_personalization_operations import set_global_kill


MONITORING_SCHEMA_VERSION = "scheduling-personalization-monitoring.v1"
MONITORING_JOB_TYPE = "monitoring_snapshot"


@dataclass(frozen=True)
class MonitoringPolicy:
    minimum_effort_p90_coverage: float = 0.80
    maximum_risk_ece: float = 0.10
    maximum_deadline_miss_degradation: float = 0.0
    maximum_override_rate: float = 0.50
    maximum_undo_rate: float = 0.20
    maximum_false_intervention_rate: float = 0.20
    maximum_p95_latency_ms: float = 75.0
    maximum_update_failure_rate: float = 0.05
    maximum_drifted_share: float = 0.20
    maximum_disparity_gap: float = 0.15


@dataclass(frozen=True)
class MonitoringAlert:
    key: str
    status: str
    severity: str
    owner: str
    metric: str
    observed: Optional[float]
    threshold: str
    evaluation_window: str
    response: str
    recovery: str
    runbook: str


@dataclass(frozen=True)
class MonitoringSnapshot:
    schema_version: str
    window_start: datetime
    window_end: datetime
    alerts: tuple[MonitoringAlert, ...]
    requires_global_kill: bool
    deterministic_scheduling_available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "alerts": [asdict(item) for item in self.alerts],
            "requires_global_kill": self.requires_global_kill,
            "deterministic_scheduling_available": True,
            "contains_user_data": False,
        }


_DEFINITIONS = (
    ("hard_constraint", "hard_constraint_violations", "critical", "scheduling-oncall", "= 0", "Kill learned influence immediately; preserve deterministic scheduling.", "Investigate the violating decision, add a regression fixture, then require manual recovery approval.", "runbooks/personalization-hard-constraint.md"),
    ("deadline_non_inferiority", "deadline_miss_rate_degradation", "critical", "scheduling-oncall", "<= 0", "Kill learned influence and compare affected deadline cohorts.", "Restore only after a future-only replay is non-inferior and the incident owner signs off.", "runbooks/personalization-deadline.md"),
    ("effort_coverage", "effort_p90_coverage", "warning", "model-owner", ">= 0.80", "Freeze promotion and reduce personal influence toward the prior.", "Require minimum sample size and restored future-only coverage for two windows.", "runbooks/personalization-calibration.md"),
    ("risk_calibration", "risk_ece", "warning", "model-owner", "<= 0.10", "Freeze promotion and serve calibrated fallback confidence.", "Refit or recalibrate and pass a future-only evaluation before promotion.", "runbooks/personalization-calibration.md"),
    ("override_burden", "override_rate", "warning", "product-owner", "<= 0.50", "Pause exploration and inspect recommendation usefulness by slice.", "Resume only after burden returns below threshold without hiding overrides.", "runbooks/personalization-autonomy.md"),
    ("undo_burden", "undo_rate", "warning", "product-owner", "<= 0.20", "Pause exploration and inspect reversals and stale previews.", "Resume after the undo cause is fixed and one clean window is observed.", "runbooks/personalization-autonomy.md"),
    ("false_interventions", "false_intervention_rate", "warning", "scheduling-oncall", "<= 0.20", "Disable proactive overload interventions while retaining baseline planning.", "Replay corrected labels and require a clean evaluation window.", "runbooks/personalization-false-intervention.md"),
    ("serving_latency", "p95_latency_ms", "warning", "platform-oncall", "<= 75 ms", "Force zero-adjustment timeout fallback and inspect serving dependencies.", "Restore learned serving after latency is below budget for one full window.", "runbooks/personalization-latency.md"),
    ("update_failures", "update_failure_rate", "warning", "platform-oncall", "<= 0.05", "Keep the last eligible model and stop repeated failing refreshes.", "Repair the job cause, replay idempotently, and verify last-model continuity.", "runbooks/personalization-jobs.md"),
    ("drift", "drifted_scope_share", "warning", "model-owner", "<= 0.20", "Decay personal influence and block promotion for affected scopes.", "Require sustained recovery evidence; do not erase long-term facts automatically.", "runbooks/personalization-drift.md"),
    ("disparity", "maximum_slice_disparity_gap", "warning", "responsible-ai-owner", "<= 0.15", "Freeze promotion and inspect only sufficiently sized declared slices.", "Document remediation and pass the disparity gate before promotion.", "runbooks/personalization-disparity.md"),
    ("deletion_correctness", "deletion_correctness_rate", "critical", "privacy-oncall", "= 1.0", "Kill learned influence and prioritize deletion propagation.", "Prove deleted evidence is absent from retrieval, features, models, and aggregates before manual recovery.", "runbooks/personalization-deletion.md"),
    ("deleted_evidence_serving", "deleted_evidence_served_count", "critical", "privacy-oncall", "= 0", "Kill learned influence and invalidate affected artifacts immediately.", "Complete lineage deletion and rerun adversarial serving checks before manual recovery.", "runbooks/personalization-deletion.md"),
)


def _number(metrics: Mapping[str, Any], key: str) -> Optional[float]:
    value = metrics.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _violates(key: str, observed: float, policy: MonitoringPolicy) -> bool:
    if key in {"hard_constraint_violations", "deleted_evidence_served_count"}:
        return observed != 0
    if key == "deadline_miss_rate_degradation":
        return observed > policy.maximum_deadline_miss_degradation
    if key == "effort_p90_coverage":
        return observed < policy.minimum_effort_p90_coverage
    if key == "risk_ece":
        return observed > policy.maximum_risk_ece
    if key == "override_rate":
        return observed > policy.maximum_override_rate
    if key == "undo_rate":
        return observed > policy.maximum_undo_rate
    if key == "false_intervention_rate":
        return observed > policy.maximum_false_intervention_rate
    if key == "p95_latency_ms":
        return observed > policy.maximum_p95_latency_ms
    if key == "update_failure_rate":
        return observed > policy.maximum_update_failure_rate
    if key == "drifted_scope_share":
        return observed > policy.maximum_drifted_share
    if key == "maximum_slice_disparity_gap":
        return observed > policy.maximum_disparity_gap
    if key == "deletion_correctness_rate":
        return observed < 1.0
    raise ValueError(f"unknown monitoring metric: {key}")


def evaluate_monitoring_window(
    *,
    window_start: datetime,
    window_end: datetime,
    metrics: Mapping[str, Any],
    previous_firing: frozenset[str] = frozenset(),
    policy: MonitoringPolicy = MonitoringPolicy(),
) -> MonitoringSnapshot:
    if window_end <= window_start:
        raise ValueError("monitoring window must be positive")
    window = f"{window_start.isoformat()}/{window_end.isoformat()}"
    alerts: list[MonitoringAlert] = []
    missing_critical = False
    for key, metric, severity, owner, threshold, response, recovery, runbook in _DEFINITIONS:
        observed = _number(metrics, metric)
        if observed is None:
            status = "insufficient"
            missing_critical = missing_critical or severity == "critical"
        elif _violates(metric, observed, policy):
            status = "firing"
        elif key in previous_firing:
            status = "recovered"
        else:
            status = "healthy"
        alerts.append(MonitoringAlert(
            key, status, severity, owner, metric, observed, threshold, window,
            response, recovery, runbook,
        ))
    if missing_critical:
        alerts.append(MonitoringAlert(
            "monitoring_completeness", "firing", "critical", "platform-oncall",
            "critical_metric_presence", None, "all critical metrics present", window,
            "Kill learned influence because safety/privacy health is unknown.",
            "Repair telemetry, backfill the window, and require manual recovery approval.",
            "runbooks/personalization-monitoring-outage.md",
        ))
    requires_kill = any(item.status == "firing" and item.severity == "critical" for item in alerts)
    return MonitoringSnapshot(
        MONITORING_SCHEMA_VERSION, window_start, window_end, tuple(alerts), requires_kill
    )


def record_monitoring_snapshot(
    db: Session,
    snapshot: MonitoringSnapshot,
    *,
    idempotency_key: str,
) -> SchedulingGovernanceJob:
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValueError("idempotency_key is required and bounded")
    stable_key = f"monitoring:{idempotency_key}"
    existing = db.query(SchedulingGovernanceJob).filter_by(idempotency_key=stable_key).one_or_none()
    if existing is not None:
        return existing
    now = utc_now_naive()
    row = SchedulingGovernanceJob(
        job_id=str(uuid4()), idempotency_key=stable_key, user_id=None,
        job_type=MONITORING_JOB_TYPE, status="succeeded",
        payload_json=snapshot.to_dict(), attempts=1, completed_at=now,
    )
    db.add(row)
    db.flush()
    if snapshot.requires_global_kill:
        firing = ",".join(
            item.key for item in snapshot.alerts
            if item.status == "firing" and item.severity == "critical"
        )
        set_global_kill(
            db, active=True, reason=f"monitoring:{firing}"[:255], actor="monitoring",
            idempotency_key=f"monitoring:{idempotency_key}",
        )
    return row
