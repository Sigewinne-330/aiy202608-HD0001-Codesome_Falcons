"""Strict date-native API contracts for schedule balancing."""

from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScheduleSourceType(str, Enum):
    task = "task"
    subtask = "subtask"
    deadline = "deadline"


class ScheduleProfile(str, Enum):
    conservative = "conservative"
    balanced = "balanced"
    sprint = "sprint"


class ScheduleDecision(str, Enum):
    keep_original = "keep_original"
    accept_recommendation = "accept_recommendation"
    choose_date = "choose_date"


class SchedulingPreferenceBase(BaseModel):
    default_capacity_hours: float = Field(default=4.0, ge=0, le=24)
    reserve_ratio: float = Field(default=0.20, ge=0, lt=1)
    balanced_target_ratio: float = Field(default=0.85, gt=0, le=1.5)
    min_chunk_hours: float = Field(default=0.5, gt=0, le=12)
    max_chunk_hours: float = Field(default=2.0, gt=0, le=24)
    # The supplied flowchart fixes the intervention boundary at the projected
    # fourth item. Keep the persisted column for compatibility, but reject
    # attempts to tune this safety/interaction rule through the API.
    max_major_items_per_date: int = Field(default=3, ge=3, le=3)
    same_kind_soft_limit: int = Field(default=2, ge=1, le=20)
    switching_soft_limit: int = Field(default=3, ge=1, le=20)
    no_deadline_horizon_days: int = Field(default=30, ge=1, le=365)
    auto_scheduling_enabled: bool = False
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_chunks(self):
        if self.min_chunk_hours > self.max_chunk_hours:
            raise ValueError("min_chunk_hours cannot exceed max_chunk_hours")
        return self

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class SchedulingPreferenceUpdate(SchedulingPreferenceBase):
    version: Optional[int] = Field(default=None, ge=1)


class SchedulingPreferenceResponse(SchedulingPreferenceBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    version: int


class CapacityOverrideUpsert(BaseModel):
    local_date: date
    capacity_hours: float = Field(ge=0, le=24)
    note: Optional[str] = Field(default=None, max_length=255)
    version: Optional[int] = Field(default=None, ge=1)


class CapacityOverrideResponse(CapacityOverrideUpsert):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    version: int


class ScheduleItemInput(BaseModel):
    source_type: ScheduleSourceType
    source_id: Optional[int] = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    subject: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, pattern="^(IA|EE|TOK|CAS)$")
    target_date: date
    parent_task_id: Optional[int] = Field(default=None, ge=1)
    estimated_hours: Optional[float] = Field(default=None, ge=0, le=24)
    energy_intensity: float = Field(default=1.0, ge=0.5, le=2.0)
    effort_source: str = Field(default="user", max_length=20)
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")
    task_type: str = Field(default="todo", pattern="^(todo|process)$")
    status: str = Field(default="todo", pattern="^(pending|todo|in_progress|done|overdue)$")
    hard_deadline_date: Optional[date] = None
    earliest_start_date: Optional[date] = None
    schedule_kind: Optional[str] = Field(default=None, max_length=50)
    is_schedule_locked: bool = False

    @model_validator(mode="after")
    def validate_date_window(self):
        if self.earliest_start_date and self.hard_deadline_date:
            if self.earliest_start_date > self.hard_deadline_date:
                raise ValueError("earliest_start_date cannot exceed hard_deadline_date")
        if self.source_type == ScheduleSourceType.subtask and self.parent_task_id is None:
            raise ValueError("parent_task_id is required for a subtask")
        return self

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return value.upper() if isinstance(value, str) and value else value


class AnalysisRequest(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    profile: ScheduleProfile = ScheduleProfile.balanced

    @model_validator(mode="after")
    def validate_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date cannot exceed end_date")
        return self


class PreflightRequest(ScheduleItemInput):
    correlation_id: Optional[str] = Field(default=None, max_length=64)


class InterventionResolveRequest(BaseModel):
    decision: ScheduleDecision
    selected_date: Optional[date] = None
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def require_selected_date(self):
        if self.decision == ScheduleDecision.choose_date and self.selected_date is None:
            raise ValueError("selected_date is required when decision is choose_date")
        return self


class PlanCreateRequest(BaseModel):
    profile: Optional[ScheduleProfile] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=128)


class PlanApplyRequest(BaseModel):
    expected_input_revision: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PlanUndoRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class HistoryQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    before_id: Optional[int] = Field(default=None, ge=1)


class ScoreBreakdown(BaseModel):
    terms: Dict[str, float] = Field(default_factory=dict)
    weights: Dict[str, float] = Field(default_factory=dict)
    total: float = 0.0


class Recommendation(BaseModel):
    date: date
    projected_count: int
    projected_hours: float
    projected_energy: float
    capacity_hours: float
    usable_capacity_hours: float
    energy_ratio: float
    score: float
    score_breakdown: ScoreBreakdown
    recommended_effort_hours: float
    increase_effort: bool
    reason_codes: List[str] = Field(default_factory=list)
    counterfactual: Optional[str] = None
    baseline_rank: Optional[int] = None
    personalized_rank: Optional[int] = None
    learned_adjustment: Optional[float] = None
    display_rank: Optional[int] = None
    model_version: Optional[str] = None
    randomized_assignment: bool = False
    assignment_probability: Optional[float] = None
    assignment_denominator: Optional[int] = None


class InterventionResponse(BaseModel):
    kind: str
    intervention_id: Optional[int] = None
    state: str
    source_type: ScheduleSourceType
    requested_date: date
    projected_count: int
    complete_day: List[Dict[str, Any]] = Field(default_factory=list)
    recommendation: Optional[Recommendation] = None
    alternatives: List[Recommendation] = Field(default_factory=list)
    clarification_question: Optional[str] = None
    clarification_reason_code: Optional[str] = None
    clarification_sensitivity: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    input_revision: Optional[str] = None
    correlation_id: Optional[str] = None
    personalization: Optional[Dict[str, Any]] = None


class AnalysisResponse(BaseModel):
    input_revision: str
    algorithm_version: str
    profile: ScheduleProfile
    dates: List[Dict[str, Any]] = Field(default_factory=list)
    feasible: bool = True
    blockers: List[str] = Field(default_factory=list)


class PlanResponse(BaseModel):
    id: int
    user_id: int
    profile: ScheduleProfile
    algorithm_version: str
    input_revision: str
    state: str
    projected_loads: List[Dict[str, Any]] = Field(default_factory=list)
    item_changes: List[Dict[str, Any]] = Field(default_factory=list)
    feasible: bool = True
    blockers: List[str] = Field(default_factory=list)
    expires_at: Any
    created_at: Any


class AuditEventResponse(BaseModel):
    id: int
    event_type: str
    actor: str
    plan_id: Optional[int] = None
    intervention_id: Optional[int] = None
    affected_items: List[Dict[str, Any]] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)
    algorithm_version: Optional[str] = None
    profile: Optional[str] = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None
    created_at: Any
