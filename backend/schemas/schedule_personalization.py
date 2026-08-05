"""Versioned contracts for adaptive scheduling observations and memory.

This module deliberately stays independent from the deterministic scheduling
contracts.  Learned systems may annotate safe candidates, but these schemas do
not grant mutation or feasibility authority.
"""

from datetime import date, datetime
from enum import Enum
import json
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EVENT_SCHEMA_VERSION = "scheduling-event.v1"
FEATURE_SCHEMA_VERSION = "scheduling-feature.v1"
MEMORY_SCHEMA_VERSION = "scheduling-memory.v1"
MODEL_SCHEMA_VERSION = "scheduling-model.v1"
CONSENT_POLICY_VERSION = "scheduling-personalization-consent.v1"
TASK_TAXONOMY_VERSION = "scheduling-task-taxonomy.v1"
EFFORT_PRIOR_VERSION = "scheduling-effort-prior.ib-v1"

MAX_STRUCTURED_PAYLOAD_BYTES = 32_768
MAX_MODEL_ARTIFACT_BYTES = 65_536


class ConsentPurpose(str, Enum):
    operational_personalization = "operational_personalization"
    work_session_capture = "work_session_capture"
    llm_memory = "llm_memory"
    cross_user_learning = "cross_user_learning"
    near_tie_exploration = "near_tie_exploration"


class WorkEventType(str, Enum):
    created = "created"
    estimated = "estimated"
    scheduled = "scheduled"
    moved = "moved"
    started = "started"
    paused = "paused"
    resumed = "resumed"
    stopped = "stopped"
    progressed = "progressed"
    completed = "completed"
    abandoned = "abandoned"
    deleted = "deleted"
    reopened = "reopened"
    deadline_changed = "deadline_changed"
    corrected = "corrected"
    outcome_observed = "outcome_observed"


class EvidenceProvenance(str, Enum):
    active_timer = "active_timer"
    direct_user = "direct_user"
    lifecycle = "lifecycle"
    imported = "imported"
    derived = "derived"
    llm_candidate = "llm_candidate"
    product_default = "product_default"


class EvidenceConfidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class CensoringReason(str, Enum):
    still_open = "still_open"
    dependency_blocked = "dependency_blocked"
    observation_window_closed = "observation_window_closed"
    offline_unknown = "offline_unknown"
    consent_withdrawn = "consent_withdrawn"
    retention_expired = "retention_expired"


class OutcomeTerminalState(str, Enum):
    completed = "completed"
    reasonably_abandoned = "reasonably_abandoned"
    deleted = "deleted"
    confirmed_miss = "confirmed_miss"
    unknown = "unknown"


class MemoryTier(str, Enum):
    explicit_declaration = "explicit_declaration"
    llm_reflection = "llm_reflection"
    temporary_context = "temporary_context"


class MemoryStatus(str, Enum):
    current = "current"
    dismissed = "dismissed"
    deleted = "deleted"
    expired = "expired"
    contradicted = "contradicted"
    superseded = "superseded"


class MemoryPurpose(str, Enum):
    extraction = "extraction"
    clarification = "clarification"
    reflection = "reflection"
    explanation = "explanation"
    ranking = "ranking"


class ModelLifecycle(str, Enum):
    candidate = "candidate"
    shadow = "shadow"
    promoted = "promoted"
    superseded = "superseded"
    killed = "killed"
    invalidated = "invalidated"


class ModelType(str, Enum):
    effort = "effort"
    completion_risk = "completion_risk"
    reranker = "reranker"


class ServingMode(str, Enum):
    disabled = "disabled"
    replay = "replay"
    shadow = "shadow"
    suggestion = "suggestion"
    killed = "killed"


class TaskArchetype(str, Enum):
    reading = "reading"
    problem_set = "problem_set"
    exam_preparation = "exam_preparation"
    research = "research"
    essay_outline = "essay_outline"
    essay_draft = "essay_draft"
    essay_revision = "essay_revision"
    laboratory = "laboratory"
    presentation = "presentation"
    long_project = "long_project"
    memorization = "memorization"
    creative = "creative"
    administration = "administration"
    mixed = "mixed"
    unknown = "unknown"


class GovernanceJobType(str, Enum):
    derive_labels = "derive_labels"
    refresh_features = "refresh_features"
    update_model = "update_model"
    evaluate_model = "evaluate_model"
    materialize_reflection = "materialize_reflection"
    enforce_retention = "enforce_retention"
    propagate_deletion = "propagate_deletion"
    detect_drift = "detect_drift"
    recompute_aggregate = "recompute_aggregate"


class GovernanceJobStatus(str, Enum):
    pending = "pending"
    leased = "leased"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


def _bounded_json(value: Any, *, maximum: int = MAX_STRUCTURED_PAYLOAD_BYTES) -> Any:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("structured value must be JSON serializable") from exc
    if len(encoded) > maximum:
        raise ValueError(f"structured value exceeds {maximum} bytes")
    return value


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceReference(StrictContract):
    source_type: str = Field(pattern="^(task|subtask|deadline)$")
    source_id: int = Field(ge=1)


class ConsentSettingsUpdate(StrictContract):
    operational_personalization_enabled: bool = False
    work_session_capture_enabled: bool = False
    llm_memory_enabled: bool = False
    cross_user_learning_enabled: bool = False
    near_tie_exploration_enabled: bool = False
    raw_event_retention_days: int = Field(default=365, ge=30, le=3650)
    rebuild_after_reset_enabled: bool = False
    expected_version: Optional[int] = Field(default=None, ge=1)
    policy_version: str = Field(default=CONSENT_POLICY_VERSION, min_length=1, max_length=64)

    @model_validator(mode="after")
    def enforce_consent_dependencies(self):
        if self.work_session_capture_enabled and not self.operational_personalization_enabled:
            raise ValueError("work-session capture requires operational personalization")
        if self.near_tie_exploration_enabled and not self.operational_personalization_enabled:
            raise ValueError("near-tie exploration requires operational personalization")
        if self.cross_user_learning_enabled and not self.operational_personalization_enabled:
            raise ValueError("cross-user learning requires operational personalization")
        if self.llm_memory_enabled and not self.operational_personalization_enabled:
            raise ValueError("LLM memory requires operational personalization")
        return self


class TaskArchetypeHypothesis(StrictContract):
    task_archetype: TaskArchetype = TaskArchetype.unknown
    subject: Optional[str] = Field(default=None, max_length=100)
    deliverable_unit: Optional[str] = Field(default=None, max_length=32)
    deliverable_quantity: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    stage: Optional[str] = Field(default=None, max_length=50)
    novelty: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")
    complexity: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")
    ambiguity: str = Field(default="high", pattern="^(low|medium|high)$")
    confidence: float = Field(default=0, ge=0, le=1)
    provenance: EvidenceProvenance = EvidenceProvenance.product_default
    schema_version: str = Field(default=FEATURE_SCHEMA_VERSION, max_length=64)
    taxonomy_version: str = Field(default=TASK_TAXONOMY_VERSION, min_length=1, max_length=64)


class DecisionCandidateContract(StrictContract):
    candidate_id: str = Field(min_length=1, max_length=128)
    local_date: date
    deterministic_rank: int = Field(ge=1, le=100)
    deterministic_score: float = Field(ge=-1_000_000, le=1_000_000)
    reason_codes: List[str] = Field(default_factory=list, max_length=20)
    effort_hours: float = Field(ge=0, le=10_000)
    energy_points: float = Field(ge=0, le=20_000)

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, value: List[str]) -> List[str]:
        if any(not code or len(code) > 64 for code in value):
            raise ValueError("reason codes must contain 1-64 characters")
        return value


class DecisionObservationInput(StrictContract):
    decision_point_id: UUID
    source: SourceReference
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=128)
    correlation_id: Optional[str] = Field(default=None, max_length=64)
    occurred_at: datetime
    local_date: date
    timezone: str = Field(min_length=1, max_length=64)
    context_hash: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
    context_snapshot: Dict[str, Any] = Field(default_factory=dict)
    candidates: List[DecisionCandidateContract] = Field(min_length=1, max_length=30)
    displayed_candidate_ids: List[str] = Field(default_factory=list, max_length=10)
    selected_candidate_id: Optional[str] = Field(default=None, max_length=128)
    selection_source: str = Field(default="unknown", max_length=32)
    automation_mode: str = Field(default="manual", pattern="^(manual|deterministic_auto)$")
    randomized_assignment: bool = False
    action_propensity: Optional[float] = Field(default=None, gt=0, le=1)
    policy_version: str = Field(min_length=1, max_length=64)
    model_version: Optional[str] = Field(default=None, max_length=64)
    consent_version: Optional[int] = Field(default=None, ge=1)
    event_schema_version: str = Field(default=EVENT_SCHEMA_VERSION, max_length=64)

    @field_validator("context_snapshot")
    @classmethod
    def validate_context_snapshot(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_json(value)

    @model_validator(mode="after")
    def validate_candidate_references(self):
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        if len(self.displayed_candidate_ids) != len(set(self.displayed_candidate_ids)):
            raise ValueError("displayed candidate IDs must be unique")
        if any(candidate_id not in ids for candidate_id in self.displayed_candidate_ids):
            raise ValueError("displayed candidates must be eligible candidates")
        selected_is_eligible = self.selected_candidate_id in ids if self.selected_candidate_id else False
        if self.selected_candidate_id and not selected_is_eligible and self.selection_source != "user_unlisted":
            raise ValueError("an unlisted selection must use selection_source=user_unlisted")
        if self.randomized_assignment:
            if len(self.displayed_candidate_ids) < 2 or self.action_propensity is None:
                raise ValueError("randomized assignment requires a multi-candidate display and known propensity")
        elif self.action_propensity is not None:
            raise ValueError("propensity is allowed only for a randomized assignment")
        return self


class WorkEventInput(StrictContract):
    event_type: WorkEventType
    source: SourceReference
    idempotency_key: str = Field(min_length=8, max_length=128)
    effective_at: Optional[datetime] = None
    progress_ratio: Optional[float] = Field(default=None, ge=0, le=1)
    active_minutes: Optional[float] = Field(default=None, ge=0, le=100_000)
    exertion: Optional[int] = Field(default=None, ge=1, le=5)
    reason_code: Optional[str] = Field(default=None, max_length=64)
    before_values: Dict[str, Any] = Field(default_factory=dict)
    after_values: Dict[str, Any] = Field(default_factory=dict)
    provenance: EvidenceProvenance = EvidenceProvenance.direct_user
    confidence: EvidenceConfidence = EvidenceConfidence.high
    correction_of_event_id: Optional[UUID] = None
    event_schema_version: str = Field(default=EVENT_SCHEMA_VERSION, max_length=64)

    @field_validator("before_values", "after_values")
    @classmethod
    def validate_structured_values(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_json(value)


class OutcomeObservationInput(StrictContract):
    source: SourceReference
    idempotency_key: str = Field(min_length=8, max_length=128)
    terminal_state: OutcomeTerminalState = OutcomeTerminalState.unknown
    actual_active_minutes: Optional[float] = Field(default=None, ge=0, le=100_000)
    progress_ratio: Optional[float] = Field(default=None, ge=0, le=1)
    reason_code: Optional[str] = Field(default=None, max_length=64)
    completed_at: Optional[datetime] = None
    correction_of_event_id: Optional[UUID] = None
    provenance: EvidenceProvenance = EvidenceProvenance.direct_user
    confidence: EvidenceConfidence = EvidenceConfidence.high


class WorkSessionStartRequest(StrictContract):
    source: SourceReference
    idempotency_key: str = Field(min_length=8, max_length=128)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class WorkSessionTransitionRequest(StrictContract):
    idempotency_key: str = Field(min_length=8, max_length=128)


class WorkSessionStopRequest(WorkSessionTransitionRequest):
    reconciliation_action: Optional[str] = Field(default=None, pattern="^(stop|discard)$")
    effective_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_reconciliation(self):
        if bool(self.reconciliation_action) != bool(self.effective_at):
            raise ValueError("reconciliation_action and effective_at must be provided together")
        return self


class PersonalizationResetRequest(StrictContract):
    idempotency_key: str = Field(min_length=8, max_length=128)
    rebuild_from_retained_evidence: bool = False
    expected_settings_version: Optional[int] = Field(default=None, ge=1)


class MemoryEntryInput(StrictContract):
    tier: MemoryTier
    memory_key: str = Field(min_length=1, max_length=100)
    value_json: Dict[str, Any] = Field(default_factory=dict)
    display_text: str = Field(min_length=1, max_length=1000)
    evidence_event_ids: List[UUID] = Field(default_factory=list, max_length=100)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    schema_version: str = Field(default=MEMORY_SCHEMA_VERSION, max_length=64)

    @field_validator("value_json")
    @classmethod
    def validate_value_json(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_json(value)

    @model_validator(mode="after")
    def validate_authority_and_window(self):
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("valid_from cannot exceed valid_until")
        if self.tier == MemoryTier.llm_reflection:
            if not self.evidence_event_ids:
                raise ValueError("LLM reflections require evidence")
            if self.confidence is None:
                raise ValueError("LLM reflections require confidence")
        return self


class MemoryEntryUpdate(StrictContract):
    value_json: Optional[Dict[str, Any]] = None
    display_text: Optional[str] = Field(default=None, min_length=1, max_length=1000)
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None

    @field_validator("value_json")
    @classmethod
    def validate_value_json(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return _bounded_json(value) if value is not None else value

    @model_validator(mode="after")
    def validate_update(self):
        if all(value is None for value in (self.value_json, self.display_text, self.valid_from, self.valid_until)):
            raise ValueError("at least one editable memory field is required")
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("valid_from cannot exceed valid_until")
        return self


class ModelArtifactContract(StrictContract):
    model_type: ModelType
    lifecycle: ModelLifecycle = ModelLifecycle.candidate
    feature_schema_version: str = Field(default=FEATURE_SCHEMA_VERSION, max_length=64)
    model_schema_version: str = Field(default=MODEL_SCHEMA_VERSION, max_length=64)
    artifact_json: Dict[str, Any]
    metrics_json: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_json")
    @classmethod
    def validate_artifact(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_json(value, maximum=MAX_MODEL_ARTIFACT_BYTES)

    @field_validator("metrics_json")
    @classmethod
    def validate_metrics(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_json(value)


class GlobalKillRequest(StrictContract):
    active: bool
    reason: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ModelKillRequest(StrictContract):
    reason: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=8, max_length=128)
    algorithm_version: str = Field(min_length=1, max_length=64)
    feature_schema_version: str = Field(min_length=1, max_length=64)
    label_version: Optional[str] = Field(default=None, max_length=64)
    calibration_version: Optional[str] = Field(default=None, max_length=64)
