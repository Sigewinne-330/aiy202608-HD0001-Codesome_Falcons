"""Non-secret schema readiness check for adaptive scheduling memory."""

from typing import Any, Dict

from sqlalchemy import inspect

from database import Base, engine
import models  # noqa: F401 - register every model before metadata comparison


REQUIRED_COLUMNS = {
    "scheduling_consent_settings": {
        "user_id", "policy_version", "version", "eligibility_watermark",
        "operational_personalization_enabled", "work_session_capture_enabled",
        "llm_memory_enabled", "cross_user_learning_enabled",
        "near_tie_exploration_enabled", "raw_event_retention_days",
    },
    "scheduling_consent_revisions": {"user_id", "version", "settings_snapshot"},
    "scheduling_decision_events": {
        "decision_point_id", "user_id", "candidate_snapshot", "displayed_candidate_ids",
        "policy_version", "consent_version", "eligibility_watermark", "invalidated_at",
    },
    "scheduling_work_sessions": {"public_id", "user_id", "active_key", "state", "version"},
    "scheduling_work_events": {
        "event_id", "user_id", "idempotency_key", "event_type", "provenance",
        "confidence", "eligibility_watermark", "invalidated_at",
    },
    "scheduling_outcome_labels": {
        "user_id", "derivation_version", "terminal_state", "is_censored",
        "censoring_reason", "eligible_personal", "invalidated_at",
    },
    "scheduling_memory_entries": {
        "memory_id", "user_id", "tier", "evidence_event_ids", "status",
        "suppression_fingerprint", "eligibility_watermark", "deleted_at",
    },
    "scheduling_feature_snapshots": {
        "user_id", "feature_schema_version", "source_eligibility_watermark",
        "effective_sample_size", "sufficient_statistics", "invalidated_at",
    },
    "scheduling_model_registry": {
        "model_id", "user_id", "model_type", "lifecycle", "artifact_json",
        "evaluation_metrics", "source_eligibility_watermark", "invalidated_at",
    },
    "scheduling_model_predictions": {
        "prediction_id", "user_id", "context_hash", "serving_mode",
        "learned_adjustment", "eligibility_watermark", "invalidated_at",
    },
    "scheduling_governance_jobs": {
        "job_id", "idempotency_key", "job_type", "status", "lease_expires_at",
    },
}

REQUIRED_INDEXES = {
    "scheduling_consent_settings": {"ix_sched_consent_user_version"},
    "scheduling_decision_events": {
        "ix_sched_decision_user_time", "ix_sched_decision_source", "ix_sched_decision_retention",
    },
    "scheduling_work_sessions": {"ix_sched_work_session_user_state", "ix_sched_work_session_source"},
    "scheduling_work_events": {"ix_sched_work_event_user_time", "ix_sched_work_event_source"},
    "scheduling_outcome_labels": {"ix_sched_outcome_eligibility"},
    "scheduling_memory_entries": {"ix_sched_memory_user_status", "ix_sched_memory_suppression"},
    "scheduling_feature_snapshots": {"ix_sched_feature_user_reference"},
    "scheduling_model_registry": {"ix_sched_model_serving"},
    "scheduling_model_predictions": {"ix_sched_prediction_user_time"},
    "scheduling_governance_jobs": {"ix_sched_governance_job_claim"},
}


def inspect_personalization_schema(engine_obj) -> Dict[str, Any]:
    inspector = inspect(engine_obj)
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(set(REQUIRED_COLUMNS) - existing_tables)
    missing_columns: Dict[str, list] = {}
    missing_indexes: Dict[str, list] = {}

    for table_name, required in REQUIRED_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing = sorted(required - actual_columns)
        if missing:
            missing_columns[table_name] = missing

    for table_name, required in REQUIRED_INDEXES.items():
        if table_name not in existing_tables:
            continue
        actual_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        missing = sorted(required - actual_indexes)
        if missing:
            missing_indexes[table_name] = missing

    model_tables = set(Base.metadata.tables)
    metadata_missing = sorted(set(REQUIRED_COLUMNS) - model_tables)
    return {
        "ok": not (missing_tables or missing_columns or missing_indexes or metadata_missing),
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "missing_indexes": missing_indexes,
        "metadata_missing": metadata_missing,
        "checked_tables": sorted(REQUIRED_COLUMNS),
    }


def main() -> int:
    result = inspect_personalization_schema(engine)
    print(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
