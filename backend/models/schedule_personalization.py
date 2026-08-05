"""Persistence for consented adaptive scheduling and long-term memory.

The tables are intentionally separate from operational schedule audit.  They
store bounded structured evidence, derived state, and model data; they never
grant permission to mutate deterministic plans.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DECIMAL,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import func

from database import Base


class SchedulingConsentSetting(Base):
    __tablename__ = "scheduling_consent_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)
    operational_personalization_enabled = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    work_session_capture_enabled = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    llm_memory_enabled = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    cross_user_learning_enabled = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    near_tie_exploration_enabled = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    raw_event_retention_days = Column(Integer, nullable=False, default=365, server_default=text("365"))
    rebuild_after_reset_enabled = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    policy_version = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    eligibility_watermark = Column(Integer, nullable=False, default=1, server_default=text("1"))
    accepted_at = Column(TIMESTAMP, nullable=True)
    withdrawn_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "raw_event_retention_days BETWEEN 30 AND 3650",
            name="ck_sched_consent_retention_days",
        ),
        CheckConstraint("version >= 1", name="ck_sched_consent_version"),
        Index("ix_sched_consent_user_version", "user_id", "version"),
    )


class SchedulingConsentRevision(Base):
    __tablename__ = "scheduling_consent_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    policy_version = Column(String(64), nullable=False)
    settings_snapshot = Column(JSON, nullable=False)
    change_source = Column(String(32), nullable=False, default="user")
    changed_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_sched_consent_revision"),
        Index("ix_sched_consent_revision_time", "user_id", "changed_at", "id"),
    )


class SchedulingDecisionEvent(Base):
    __tablename__ = "scheduling_decision_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_point_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(Integer, nullable=False)
    correlation_id = Column(String(64), nullable=True)
    idempotency_key = Column(String(128), nullable=True)
    occurred_at = Column(TIMESTAMP, nullable=False)
    local_date = Column(Date, nullable=False)
    timezone = Column(String(64), nullable=False)
    event_schema_version = Column(String(64), nullable=False)
    context_hash = Column(String(64), nullable=False)
    context_snapshot = Column(JSON, nullable=False, default=dict)
    candidate_snapshot = Column(JSON, nullable=False)
    displayed_candidate_ids = Column(JSON, nullable=False, default=list)
    selected_candidate_id = Column(String(128), nullable=True)
    selection_source = Column(String(32), nullable=False, default="unknown")
    automation_mode = Column(String(32), nullable=False, default="manual")
    action_propensity = Column(DECIMAL(8, 7), nullable=True)
    policy_version = Column(String(64), nullable=False)
    model_version = Column(String(64), nullable=True)
    consent_version = Column(Integer, nullable=True)
    eligible_personal = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    eligible_cross_user = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    eligibility_watermark = Column(Integer, nullable=False, default=1, server_default=text("1"))
    retention_expires_at = Column(TIMESTAMP, nullable=True)
    invalidated_at = Column(TIMESTAMP, nullable=True)
    outcome_link_status = Column(String(32), nullable=False, default="pending")
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_sched_decision_idempotency"),
        CheckConstraint(
            "action_propensity IS NULL OR (action_propensity > 0 AND action_propensity <= 1)",
            name="ck_sched_decision_propensity",
        ),
        Index("ix_sched_decision_user_time", "user_id", "occurred_at", "id"),
        Index("ix_sched_decision_source", "user_id", "source_type", "source_id"),
        Index("ix_sched_decision_retention", "retention_expires_at", "invalidated_at"),
    )


class SchedulingWorkSession(Base):
    __tablename__ = "scheduling_work_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(Integer, nullable=False)
    active_key = Column(String(128), nullable=True, unique=True)
    state = Column(String(20), nullable=False, default="active")
    timezone = Column(String(64), nullable=False)
    started_at = Column(TIMESTAMP, nullable=False)
    current_interval_started_at = Column(TIMESTAMP, nullable=True)
    paused_at = Column(TIMESTAMP, nullable=True)
    ended_at = Column(TIMESTAMP, nullable=True)
    accumulated_active_seconds = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_event_id = Column(String(36), nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "state IN ('active','paused','stopped','discarded')",
            name="ck_sched_work_session_state",
        ),
        CheckConstraint("accumulated_active_seconds >= 0", name="ck_sched_work_session_seconds"),
        Index("ix_sched_work_session_user_state", "user_id", "state", "updated_at"),
        Index("ix_sched_work_session_source", "user_id", "source_type", "source_id"),
    )


class SchedulingWorkEvent(Base):
    __tablename__ = "scheduling_work_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(Integer, ForeignKey("scheduling_work_sessions.id", ondelete="SET NULL"), nullable=True)
    source_type = Column(String(32), nullable=False)
    source_id = Column(Integer, nullable=False)
    event_type = Column(String(32), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    occurred_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    effective_at = Column(TIMESTAMP, nullable=False)
    effective_local_date = Column(Date, nullable=False)
    timezone = Column(String(64), nullable=False)
    before_values = Column(JSON, nullable=False, default=dict)
    after_values = Column(JSON, nullable=False, default=dict)
    provenance = Column(String(32), nullable=False)
    confidence = Column(String(16), nullable=False)
    correction_of_event_id = Column(String(36), nullable=True)
    decision_point_id = Column(String(36), nullable=True)
    plan_id = Column(Integer, nullable=True)
    consent_version = Column(Integer, nullable=True)
    event_schema_version = Column(String(64), nullable=False)
    eligible_personal = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    eligible_cross_user = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    eligibility_watermark = Column(Integer, nullable=False, default=1, server_default=text("1"))
    retention_expires_at = Column(TIMESTAMP, nullable=True)
    invalidated_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_sched_work_event_idempotency"),
        Index("ix_sched_work_event_user_time", "user_id", "effective_at", "id"),
        Index("ix_sched_work_event_source", "user_id", "source_type", "source_id", "effective_at"),
        Index("ix_sched_work_event_session", "session_id", "id"),
        Index("ix_sched_work_event_retention", "retention_expires_at", "invalidated_at"),
    )


class SchedulingOutcomeLabel(Base):
    __tablename__ = "scheduling_outcome_labels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(Integer, nullable=False)
    decision_point_id = Column(String(36), nullable=True)
    episode = Column(Integer, nullable=False, default=1, server_default=text("1"))
    derivation_version = Column(String(64), nullable=False)
    outcome_cutoff_at = Column(TIMESTAMP, nullable=False)
    active_minutes = Column(DECIMAL(10, 2), nullable=True)
    active_minutes_provenance = Column(String(32), nullable=True)
    interval_complete = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    start_latency_minutes = Column(DECIMAL(10, 2), nullable=True)
    planned_actual_ratio = Column(DECIMAL(10, 4), nullable=True)
    progress_ratio = Column(DECIMAL(6, 5), nullable=True)
    completed_before_personal_target = Column(Boolean, nullable=True)
    completed_before_hard_deadline = Column(Boolean, nullable=True)
    terminal_state = Column(String(32), nullable=False, default="unknown")
    is_censored = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    censoring_reason = Column(String(32), nullable=True)
    censored_at = Column(TIMESTAMP, nullable=True)
    label_confidence = Column(String(16), nullable=False, default="unknown")
    eligible_personal = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    eligible_evaluation = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    eligible_cross_user = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    eligibility_watermark = Column(Integer, nullable=False, default=1, server_default=text("1"))
    invalidated_at = Column(TIMESTAMP, nullable=True)
    derived_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_type", "source_id", "episode", "derivation_version", "outcome_cutoff_at",
            name="uq_sched_outcome_derivation",
        ),
        CheckConstraint(
            "progress_ratio IS NULL OR (progress_ratio >= 0 AND progress_ratio <= 1)",
            name="ck_sched_outcome_progress",
        ),
        Index("ix_sched_outcome_user_source", "user_id", "source_type", "source_id", "episode"),
        Index("ix_sched_outcome_eligibility", "user_id", "eligible_personal", "invalidated_at"),
    )


class SchedulingMemoryEntry(Base):
    __tablename__ = "scheduling_memory_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    tier = Column(String(32), nullable=False)
    memory_key = Column(String(100), nullable=False)
    value_json = Column(JSON, nullable=False, default=dict)
    display_text = Column(Text, nullable=False)
    source = Column(String(32), nullable=False)
    evidence_event_ids = Column(JSON, nullable=False, default=list)
    evidence_hash = Column(String(64), nullable=True)
    evidence_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    confidence = Column(DECIMAL(6, 5), nullable=True)
    maturity = Column(DECIMAL(6, 5), nullable=True)
    valid_from = Column(Date, nullable=True)
    valid_until = Column(Date, nullable=True)
    expires_at = Column(TIMESTAMP, nullable=True)
    supersedes_memory_id = Column(String(36), nullable=True)
    superseded_by_memory_id = Column(String(36), nullable=True)
    contradiction_state = Column(String(32), nullable=False, default="none")
    generated_by_model = Column(String(128), nullable=True)
    prompt_version = Column(String(64), nullable=True)
    schema_version = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="current")
    suppression_fingerprint = Column(String(64), nullable=True)
    consent_version = Column(Integer, nullable=True)
    eligibility_watermark = Column(Integer, nullable=False, default=1, server_default=text("1"))
    last_retrieved_at = Column(TIMESTAMP, nullable=True)
    last_used_purpose = Column(String(32), nullable=True)
    invalidated_at = Column(TIMESTAMP, nullable=True)
    deleted_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_sched_memory_user_status", "user_id", "status", "tier", "updated_at"),
        Index("ix_sched_memory_user_key", "user_id", "memory_key", "valid_until"),
        Index("ix_sched_memory_evidence_hash", "user_id", "evidence_hash", "status"),
        Index("ix_sched_memory_suppression", "user_id", "suppression_fingerprint", "status"),
    )


class SchedulingFeatureSnapshot(Base):
    __tablename__ = "scheduling_feature_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    scope_type = Column(String(32), nullable=False)
    scope_key = Column(String(191), nullable=False)
    reference_date = Column(Date, nullable=False)
    window_start = Column(Date, nullable=True)
    window_end = Column(Date, nullable=True)
    feature_schema_version = Column(String(64), nullable=False)
    source_eligibility_watermark = Column(Integer, nullable=False)
    effective_sample_size = Column(DECIMAL(12, 4), nullable=False, default=0)
    sufficient_statistics = Column(JSON, nullable=False)
    recent_statistics = Column(JSON, nullable=False, default=dict)
    recency_policy = Column(JSON, nullable=False, default=dict)
    drift_state = Column(String(20), nullable=False, default="stable")
    eligible_cross_user = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    invalidated_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "user_id", "scope_type", "scope_key", "reference_date", "feature_schema_version",
            name="uq_sched_feature_snapshot",
        ),
        Index("ix_sched_feature_user_reference", "user_id", "reference_date", "id"),
        Index("ix_sched_feature_scope", "scope_type", "scope_key", "reference_date"),
    )


class SchedulingModelRegistry(Base):
    __tablename__ = "scheduling_model_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True)
    model_type = Column(String(32), nullable=False)
    scope = Column(String(32), nullable=False)
    lifecycle = Column(String(20), nullable=False, default="candidate")
    algorithm_version = Column(String(64), nullable=False)
    feature_schema_version = Column(String(64), nullable=False)
    label_version = Column(String(64), nullable=True)
    calibration_version = Column(String(64), nullable=True)
    source_eligibility_watermark = Column(Integer, nullable=False, default=1, server_default=text("1"))
    training_window_start = Column(TIMESTAMP, nullable=True)
    training_window_end = Column(TIMESTAMP, nullable=True)
    effective_sample_size = Column(DECIMAL(12, 4), nullable=False, default=0)
    artifact_json = Column(JSON, nullable=False)
    evaluation_metrics = Column(JSON, nullable=False, default=dict)
    slice_metrics = Column(JSON, nullable=False, default=dict)
    fallback_model_id = Column(Integer, ForeignKey("scheduling_model_registry.id", ondelete="SET NULL"), nullable=True)
    serving_started_at = Column(TIMESTAMP, nullable=True)
    serving_ended_at = Column(TIMESTAMP, nullable=True)
    lifecycle_reason = Column(String(255), nullable=True)
    approved_by = Column(String(64), nullable=True)
    invalidated_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('candidate','shadow','promoted','superseded','killed','invalidated')",
            name="ck_sched_model_lifecycle",
        ),
        Index("ix_sched_model_serving", "user_id", "model_type", "lifecycle", "created_at"),
        Index("ix_sched_model_scope", "scope", "model_type", "created_at"),
    )


class SchedulingModelPrediction(Base):
    __tablename__ = "scheduling_model_predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prediction_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    decision_point_id = Column(String(36), nullable=True)
    model_registry_id = Column(Integer, ForeignKey("scheduling_model_registry.id", ondelete="SET NULL"), nullable=True)
    context_hash = Column(String(64), nullable=False)
    prediction_type = Column(String(32), nullable=False)
    horizon_date = Column(Date, nullable=True)
    p10 = Column(DECIMAL(12, 4), nullable=True)
    p50 = Column(DECIMAL(12, 4), nullable=True)
    p90 = Column(DECIMAL(12, 4), nullable=True)
    probability = Column(DECIMAL(8, 7), nullable=True)
    evidence_maturity = Column(DECIMAL(6, 5), nullable=False, default=0)
    calibration_state = Column(String(20), nullable=False, default="unknown")
    feature_contributions = Column(JSON, nullable=False, default=dict)
    baseline_rank = Column(Integer, nullable=True)
    learned_rank = Column(Integer, nullable=True)
    learned_adjustment = Column(DECIMAL(12, 6), nullable=False, default=0)
    serving_mode = Column(String(20), nullable=False)
    latency_ms = Column(Integer, nullable=False, default=0)
    consent_version = Column(Integer, nullable=True)
    eligibility_watermark = Column(Integer, nullable=False, default=1, server_default=text("1"))
    invalidated_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 1)",
            name="ck_sched_prediction_probability",
        ),
        Index("ix_sched_prediction_user_time", "user_id", "created_at", "id"),
        Index("ix_sched_prediction_decision", "decision_point_id", "prediction_type"),
    )


class SchedulingGovernanceJob(Base):
    __tablename__ = "scheduling_governance_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), nullable=False, unique=True)
    idempotency_key = Column(String(191), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True)
    job_type = Column(String(32), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    payload_json = Column(JSON, nullable=False, default=dict)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    not_before = Column(TIMESTAMP, nullable=True)
    lease_owner = Column(String(128), nullable=True)
    lease_expires_at = Column(TIMESTAMP, nullable=True)
    last_error_code = Column(String(64), nullable=True)
    last_error_detail = Column(String(500), nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','leased','succeeded','failed','cancelled')",
            name="ck_sched_governance_job_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_sched_governance_job_attempts"),
        Index("ix_sched_governance_job_claim", "status", "not_before", "lease_expires_at", "id"),
        Index("ix_sched_governance_job_user", "user_id", "job_type", "created_at"),
    )
