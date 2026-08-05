"""Persistence models for date-level workload balancing.

The models intentionally use generic source references for allocations and
plan items.  The projection service validates ownership and source existence
before any recommendation or mutation, which keeps legacy tables compatible
while allowing tasks, subtasks, and deadlines to share one planner.
"""

from sqlalchemy import (
    Boolean,
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
)
from sqlalchemy.sql import func

from database import Base


class SchedulingPreference(Base):
    __tablename__ = "scheduling_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)
    default_capacity_hours = Column(DECIMAL(5, 2), nullable=False, default=4.0)
    reserve_ratio = Column(DECIMAL(4, 3), nullable=False, default=0.20)
    balanced_target_ratio = Column(DECIMAL(4, 3), nullable=False, default=0.85)
    min_chunk_hours = Column(DECIMAL(5, 2), nullable=False, default=0.5)
    max_chunk_hours = Column(DECIMAL(5, 2), nullable=False, default=2.0)
    max_major_items_per_date = Column(Integer, nullable=False, default=3)
    same_kind_soft_limit = Column(Integer, nullable=False, default=2)
    switching_soft_limit = Column(Integer, nullable=False, default=3)
    no_deadline_horizon_days = Column(Integer, nullable=False, default=30)
    auto_scheduling_enabled = Column(Boolean, nullable=False, default=False)
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class ScheduleCapacityOverride(Base):
    __tablename__ = "schedule_capacity_overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    local_date = Column(Date, nullable=False)
    capacity_hours = Column(DECIMAL(5, 2), nullable=False)
    note = Column(String(255), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_schedule_capacity_user_date"),
        Index("ix_schedule_capacity_user_date", "user_id", "local_date"),
    )


class ScheduleItemDependency(Base):
    __tablename__ = "schedule_item_dependencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    predecessor_type = Column(String(32), nullable=False)
    predecessor_id = Column(Integer, nullable=False)
    successor_type = Column(String(32), nullable=False)
    successor_id = Column(Integer, nullable=False)
    relation_type = Column(String(32), nullable=False, default="finish_to_start")
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "user_id", "predecessor_type", "predecessor_id",
            "successor_type", "successor_id", "relation_type",
            name="uq_schedule_dependency_edge",
        ),
        Index("ix_schedule_dependency_user", "user_id"),
    )


class ScheduleAllocation(Base):
    __tablename__ = "schedule_allocations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(Integer, nullable=False)
    local_date = Column(Date, nullable=False)
    effort_hours = Column(DECIMAL(5, 2), nullable=False)
    energy_points = Column(DECIMAL(7, 2), nullable=False, default=0)
    state = Column(String(20), nullable=False, default="active")
    source_plan_item_id = Column(Integer, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_schedule_allocation_user_date", "user_id", "local_date"),
        Index("ix_schedule_allocation_source", "user_id", "source_type", "source_id"),
    )


class ScheduleIntervention(Base):
    __tablename__ = "schedule_interventions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False)
    provisional_payload = Column(JSON, nullable=False)
    target_date = Column(Date, nullable=False)
    input_revision = Column(String(64), nullable=False)
    projected_count = Column(Integer, nullable=False)
    ranked_recommendations = Column(JSON, nullable=False)
    state = Column(String(32), nullable=False, default="pending")
    decision = Column(String(32), nullable=True)
    selected_date = Column(Date, nullable=True)
    resolution_idempotency_key = Column(String(128), nullable=True)
    correlation_id = Column(String(64), nullable=False)
    expires_at = Column(TIMESTAMP, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    resolved_at = Column(TIMESTAMP, nullable=True)

    __table_args__ = (
        Index("ix_schedule_intervention_user_state", "user_id", "state"),
    )


class SchedulePlan(Base):
    __tablename__ = "schedule_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    profile = Column(String(20), nullable=False)
    algorithm_version = Column(String(64), nullable=False)
    input_revision = Column(String(64), nullable=False)
    config_snapshot = Column(JSON, nullable=False)
    projected_loads = Column(JSON, nullable=False)
    state = Column(String(20), nullable=False, default="preview")
    idempotency_key = Column(String(128), nullable=True)
    result_snapshot = Column(JSON, nullable=True)
    supersedes_plan_id = Column(Integer, nullable=True)
    undo_of_plan_id = Column(Integer, nullable=True)
    expires_at = Column(TIMESTAMP, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    applied_at = Column(TIMESTAMP, nullable=True)

    __table_args__ = (
        Index("ix_schedule_plan_user_state", "user_id", "state"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_schedule_plan_idempotency"),
    )


class SchedulePlanItem(Base):
    __tablename__ = "schedule_plan_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("schedule_plans.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_id = Column(Integer, nullable=False)
    before_date = Column(Date, nullable=True)
    after_date = Column(Date, nullable=True)
    before_version = Column(Integer, nullable=False, default=1)
    after_version = Column(Integer, nullable=False, default=1)
    before_values = Column(JSON, nullable=False)
    after_values = Column(JSON, nullable=False)
    effort_hours = Column(DECIMAL(5, 2), nullable=False, default=0)
    score = Column(DECIMAL(12, 6), nullable=False, default=0)
    reason_codes = Column(JSON, nullable=False, default=list)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        Index("ix_schedule_plan_item_plan", "plan_id"),
        Index("ix_schedule_plan_item_source", "source_type", "source_id"),
    )


class ScheduleAuditEvent(Base):
    __tablename__ = "schedule_audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(32), nullable=False)
    actor = Column(String(32), nullable=False, default="user")
    plan_id = Column(Integer, nullable=True)
    intervention_id = Column(Integer, nullable=True)
    affected_items = Column(JSON, nullable=False, default=list)
    reason_codes = Column(JSON, nullable=False, default=list)
    algorithm_version = Column(String(64), nullable=True)
    profile = Column(String(20), nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    correlation_id = Column(String(64), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        Index("ix_schedule_audit_user_time", "user_id", "created_at", "id"),
    )
