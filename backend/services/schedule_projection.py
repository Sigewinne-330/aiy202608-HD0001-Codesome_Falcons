"""Read-only, owner-scoped normalization of calendar workload."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from models.deadline import Deadline
from models.scheduling import (
    ScheduleAllocation,
    ScheduleCapacityOverride,
    ScheduleItemDependency,
    SchedulingPreference,
)
from models.sub_task import SubTask
from models.task_new import Task
from services.schedule_policy import DEFAULT_PREFERENCES, bounded_effort, bounded_intensity


ACTIVE_TASK_STATUSES = {"todo", "pending", "in_progress", "overdue"}
DONE_STATUSES = {"done", "cancelled", "canceled", "complete", "completed"}
PRIORITY_WEIGHT = {"low": 0.75, "medium": 1.0, "high": 1.35, "urgent": 1.8}


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _decimal_float(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class WorkItem:
    source_type: str
    source_id: int
    user_id: int
    title: str
    local_date: Optional[date]
    status: str
    priority: str
    estimated_hours: float
    energy_intensity: float
    effort_source: str
    is_schedule_locked: bool
    schedule_kind: str
    hard_deadline_date: Optional[date] = None
    earliest_start_date: Optional[date] = None
    parent_task_id: Optional[int] = None
    deferral_count: int = 0
    schedule_version: int = 1
    progress: int = 0
    task_type: str = "todo"
    flexible: bool = True
    metadata: Dict = field(default_factory=dict, compare=False)

    @property
    def key(self) -> str:
        return f"{self.source_type}:{self.source_id}"

    @property
    def energy(self) -> float:
        return round(self.estimated_hours * self.energy_intensity, 6)

    @property
    def priority_weight(self) -> float:
        return PRIORITY_WEIGHT.get(self.priority, 1.0)


@dataclass(frozen=True)
class DependencyEdge:
    predecessor: str
    successor: str
    relation_type: str = "finish_to_start"


@dataclass(frozen=True)
class CapacityPolicy:
    default_capacity_hours: float
    reserve_ratio: float
    balanced_target_ratio: float
    min_chunk_hours: float
    max_chunk_hours: float
    max_major_items_per_date: int
    same_kind_soft_limit: int
    switching_soft_limit: int
    no_deadline_horizon_days: int
    auto_scheduling_enabled: bool
    timezone: str
    version: int = 0

    @property
    def usable_default_hours(self) -> float:
        return self.default_capacity_hours * (1.0 - self.reserve_ratio)


@dataclass(frozen=True)
class ScheduleSnapshot:
    user_id: int
    items: Tuple[WorkItem, ...]
    dependencies: Tuple[DependencyEdge, ...]
    preferences: CapacityPolicy
    capacity_overrides: Dict[date, float]
    revision: str

    @property
    def local_today(self) -> date:
        """Return today's date in the user's configured scheduling timezone."""
        return datetime.now(ZoneInfo(self.preferences.timezone)).date()

    def items_on(self, local_date: date) -> List[WorkItem]:
        return [item for item in self.items if item.local_date == local_date]

    def capacity_hours(self, local_date: date) -> float:
        if local_date in self.capacity_overrides:
            return self.capacity_overrides[local_date]
        return self.preferences.default_capacity_hours

    def usable_capacity_hours(self, local_date: date) -> float:
        return self.capacity_hours(local_date) * (1.0 - self.preferences.reserve_ratio)


def _preference_values(row: Optional[SchedulingPreference]) -> dict:
    if not row:
        return dict(DEFAULT_PREFERENCES)
    return {
        key: getattr(row, key)
        for key in DEFAULT_PREFERENCES
    }


def load_capacity_policy(db: Session, user_id: int) -> CapacityPolicy:
    row = db.query(SchedulingPreference).filter(SchedulingPreference.user_id == user_id).first()
    values = _preference_values(row)
    return CapacityPolicy(
        default_capacity_hours=_decimal_float(values["default_capacity_hours"], 4.0),
        reserve_ratio=_decimal_float(values["reserve_ratio"], 0.20),
        balanced_target_ratio=_decimal_float(values["balanced_target_ratio"], 0.85),
        min_chunk_hours=_decimal_float(values["min_chunk_hours"], 0.5),
        max_chunk_hours=_decimal_float(values["max_chunk_hours"], 2.0),
        max_major_items_per_date=int(values["max_major_items_per_date"]),
        same_kind_soft_limit=int(values["same_kind_soft_limit"]),
        switching_soft_limit=int(values["switching_soft_limit"]),
        no_deadline_horizon_days=int(values["no_deadline_horizon_days"]),
        auto_scheduling_enabled=bool(values["auto_scheduling_enabled"]),
        timezone=str(values["timezone"]),
        version=int(row.version if row else 0),
    )


def _normalize_task(task: Task, has_subtasks: bool) -> Optional[WorkItem]:
    if has_subtasks or str(task.status or "todo").lower() in DONE_STATUSES:
        return None
    local_date = _as_date(task.deadline)
    if local_date is None:
        return None
    effort = _decimal_float(task.estimated_hours, 0.0)
    source = task.effort_source or ("user" if effort > 0 else "default")
    if effort <= 0:
        effort = 1.0
        source = "default"
    # ``deadline`` is the current planned date.  Only explicit hard metadata
    # (or the legacy personal deadline) constrains movement.
    hard_date = _as_date(task.hard_deadline_date) or _as_date(task.personal_deadline)
    return WorkItem(
        source_type="task",
        source_id=task.id,
        user_id=task.user_id,
        title=task.title,
        local_date=local_date,
        status=str(getattr(task.status, "value", task.status) or "todo"),
        priority=str(getattr(task.priority, "value", task.priority) or "medium"),
        estimated_hours=bounded_effort(effort),
        energy_intensity=bounded_intensity(task.energy_intensity),
        effort_source=source,
        is_schedule_locked=bool(task.is_schedule_locked),
        schedule_kind=task.schedule_kind or task.category or "task",
        hard_deadline_date=hard_date,
        earliest_start_date=_as_date(task.earliest_start_date),
        deferral_count=int(task.deferral_count or 0),
        schedule_version=int(task.schedule_version or 1),
        progress=int(task.progress or 0),
        task_type=str(getattr(task.task_type, "value", task.task_type) or "todo"),
        flexible=not bool(task.is_schedule_locked),
        metadata={"category": task.category, "subject": task.subject},
    )


def _normalize_subtask(subtask: SubTask, parent: Task) -> Optional[WorkItem]:
    if str(subtask.status or "pending").lower() in DONE_STATUSES:
        return None
    local_date = _as_date(subtask.notice_time)
    if local_date is None:
        return None
    effort = _decimal_float(subtask.estimated_hours, 0.0)
    source = subtask.effort_source or ("user" if effort > 0 else "default")
    if effort <= 0:
        effort = 1.0
        source = "default"
    hard_date = _as_date(subtask.hard_deadline_date)
    return WorkItem(
        source_type="subtask",
        source_id=subtask.id,
        user_id=parent.user_id,
        title=subtask.name,
        local_date=local_date,
        status=str(subtask.status or "pending"),
        priority=str(subtask.level or "medium"),
        estimated_hours=bounded_effort(effort),
        energy_intensity=bounded_intensity(subtask.energy_intensity),
        effort_source=source,
        is_schedule_locked=bool(subtask.is_schedule_locked),
        schedule_kind=subtask.schedule_kind or parent.category or "subtask",
        hard_deadline_date=hard_date,
        earliest_start_date=_as_date(subtask.earliest_start_date),
        parent_task_id=parent.id,
        deferral_count=int(subtask.deferral_count or 0),
        schedule_version=int(subtask.schedule_version or 1),
        task_type="todo",
        flexible=not bool(subtask.is_schedule_locked),
        metadata={"category": parent.category, "subject": parent.subject},
    )


def _normalize_deadline(deadline: Deadline) -> Optional[WorkItem]:
    status = str(getattr(deadline.status, "value", deadline.status) or "pending")
    if status.lower() in DONE_STATUSES:
        return None
    effort = _decimal_float(deadline.estimated_hours, 1.0)
    return WorkItem(
        source_type="deadline",
        source_id=deadline.id,
        user_id=deadline.user_id,
        title=deadline.title,
        local_date=_as_date(deadline.due_date),
        status=status,
        priority=str(getattr(deadline.priority, "value", deadline.priority) or "medium"),
        estimated_hours=bounded_effort(effort),
        energy_intensity=bounded_intensity(deadline.energy_intensity),
        effort_source=deadline.effort_source or "default",
        is_schedule_locked=bool(deadline.is_schedule_locked),
        schedule_kind=deadline.schedule_kind or deadline.source or "deadline",
        hard_deadline_date=_as_date(deadline.due_date),
        schedule_version=int(deadline.schedule_version or 1),
        flexible=False,
        metadata={"source": deadline.source, "subject": deadline.subject},
    )


def _canonical_revision(
    items: Iterable[WorkItem],
    dependencies: Iterable[DependencyEdge],
    preferences: CapacityPolicy,
    overrides: Dict[date, float],
    override_versions: Optional[Dict[date, int]] = None,
) -> str:
    payload = {
        "items": [
            {
                "key": item.key,
                "date": item.local_date.isoformat() if item.local_date else None,
                "status": item.status,
                "priority": item.priority,
                "hours": item.estimated_hours,
                "intensity": item.energy_intensity,
                "effort_source": item.effort_source,
                "locked": item.is_schedule_locked,
                "flexible": item.flexible,
                "kind": item.schedule_kind,
                "task_type": item.task_type,
                "progress": item.progress,
                "deferrals": item.deferral_count,
                "deadline": item.hard_deadline_date.isoformat() if item.hard_deadline_date else None,
                "earliest": item.earliest_start_date.isoformat() if item.earliest_start_date else None,
                "version": item.schedule_version,
                "allocation_id": item.metadata.get("allocation_id"),
                "allocation_version": item.metadata.get("allocation_version"),
            }
            for item in sorted(
                items,
                key=lambda row: (
                    row.key,
                    row.local_date or date.min,
                    row.metadata.get("allocation_id") or 0,
                ),
            )
        ],
        "dependencies": [asdict(edge) for edge in sorted(dependencies, key=lambda row: (row.predecessor, row.successor))],
        "preferences": asdict(preferences),
        "overrides": {
            key.isoformat(): {
                "capacity_hours": value,
                "version": int((override_versions or {}).get(key, 0)),
            }
            for key, value in sorted(overrides.items())
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_snapshot(db: Session, user_id: int) -> ScheduleSnapshot:
    tasks = db.query(Task).filter(Task.user_id == user_id).all()
    task_ids = [task.id for task in tasks]
    subtasks = (
        db.query(SubTask).filter(SubTask.task_id.in_(task_ids)).all()
        if task_ids else []
    )
    subtask_by_parent: Dict[int, List[SubTask]] = {}
    for subtask in subtasks:
        subtask_by_parent.setdefault(subtask.task_id, []).append(subtask)

    represented_parent_ids = {
        subtask.task_id
        for subtask in subtasks
        if str(subtask.status or "pending").lower() not in DONE_STATUSES
        and _as_date(subtask.notice_time) is not None
    }

    items: List[WorkItem] = []
    for task in tasks:
        normalized = _normalize_task(task, task.id in represented_parent_ids)
        if normalized:
            items.append(normalized)
    task_by_id = {task.id: task for task in tasks}
    for subtask in subtasks:
        parent = task_by_id.get(subtask.task_id)
        if parent:
            normalized = _normalize_subtask(subtask, parent)
            if normalized:
                items.append(normalized)

    for deadline in db.query(Deadline).filter(Deadline.user_id == user_id).all():
        normalized = _normalize_deadline(deadline)
        if normalized:
            items.append(normalized)

    # Applied allocations are the planned-work representation for split items.
    # When a source has active allocations, replace its single legacy date with
    # one normalized item per allocated date so count/load do not double count.
    allocation_rows = (
        db.query(ScheduleAllocation)
        .filter(ScheduleAllocation.user_id == user_id, ScheduleAllocation.state == "active")
        .order_by(ScheduleAllocation.local_date.asc(), ScheduleAllocation.id.asc())
        .all()
    )
    if allocation_rows:
        source_map = {item.key: item for item in items}
        allocated_keys = {
            f"{row.source_type}:{row.source_id}"
            for row in allocation_rows
            if f"{row.source_type}:{row.source_id}" in source_map
        }
        base_without_allocations = [item for item in items if item.key not in allocated_keys]
        for row in allocation_rows:
            source = source_map.get(f"{row.source_type}:{row.source_id}")
            if not source:
                continue
            effort = _decimal_float(row.effort_hours, source.estimated_hours)
            items.append(WorkItem(
                source_type=source.source_type,
                source_id=source.source_id,
                user_id=user_id,
                title=source.title,
                local_date=row.local_date,
                status=source.status,
                priority=source.priority,
                estimated_hours=bounded_effort(effort),
                energy_intensity=source.energy_intensity,
                effort_source="plan",
                is_schedule_locked=source.is_schedule_locked,
                schedule_kind=source.schedule_kind,
                hard_deadline_date=source.hard_deadline_date,
                earliest_start_date=source.earliest_start_date,
                parent_task_id=source.parent_task_id,
                deferral_count=source.deferral_count,
                schedule_version=source.schedule_version,
                progress=source.progress,
                task_type=source.task_type,
                flexible=source.flexible,
                metadata={
                    **source.metadata,
                    "allocation_id": row.id,
                    "allocation_version": int(row.version or 1),
                },
            ))
        items = base_without_allocations + [item for item in items if item.metadata.get("allocation_id")]

    dependency_rows = db.query(ScheduleItemDependency).filter(ScheduleItemDependency.user_id == user_id).all()
    dependencies = tuple(
        DependencyEdge(
            predecessor=f"{row.predecessor_type}:{row.predecessor_id}",
            successor=f"{row.successor_type}:{row.successor_id}",
            relation_type=row.relation_type,
        )
        for row in dependency_rows
    )

    override_rows = db.query(ScheduleCapacityOverride).filter(ScheduleCapacityOverride.user_id == user_id).all()
    overrides = {row.local_date: _decimal_float(row.capacity_hours) for row in override_rows}
    override_versions = {row.local_date: int(row.version or 1) for row in override_rows}
    preferences = load_capacity_policy(db, user_id)
    revision = _canonical_revision(items, dependencies, preferences, overrides, override_versions)
    return ScheduleSnapshot(
        user_id=user_id,
        items=tuple(sorted(items, key=lambda row: row.key)),
        dependencies=dependencies,
        preferences=preferences,
        capacity_overrides=overrides,
        revision=revision,
    )


def serialize_item(item: WorkItem) -> dict:
    return {
        "source_type": item.source_type,
        "source_id": item.source_id,
        "title": item.title,
        "date": item.local_date.isoformat() if item.local_date else None,
        "status": item.status,
        "priority": item.priority,
        "estimated_hours": item.estimated_hours,
        "energy_intensity": item.energy_intensity,
        "energy": item.energy,
        "effort_source": item.effort_source,
        "locked": item.is_schedule_locked,
        "schedule_kind": item.schedule_kind,
        "hard_deadline_date": item.hard_deadline_date.isoformat() if item.hard_deadline_date else None,
        "earliest_start_date": item.earliest_start_date.isoformat() if item.earliest_start_date else None,
        "schedule_version": item.schedule_version,
    }
