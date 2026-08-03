from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.deadline import Deadline, DeadlineStatus
from models.reminder import (
    ReminderDigest,
    ReminderDigestState,
    ReminderOccurrence,
    ReminderOccurrenceState,
)
from models.sub_task import SubTask
from models.task_new import Task, TaskType
from services.reminder_preferences import ResolvedReminderPreferences


REMINDER_LOCAL_TIME = time(hour=9, minute=0)


@dataclass(frozen=True)
class ReminderCandidate:
    item_type: str
    item_id: int
    title: str
    description: str
    due_date: date
    cadence_offset: int
    priority: str
    subject: str
    progress: Optional[int] = None

    @property
    def cadence_label(self) -> str:
        if self.cadence_offset > 0:
            return f"D-{self.cadence_offset}"
        if self.cadence_offset < 0:
            return f"D+{abs(self.cadence_offset)}"
        return "D0"

    def snapshot(self) -> dict:
        data = asdict(self)
        data["due_date"] = self.due_date.isoformat()
        data["cadence_label"] = self.cadence_label
        return data


@dataclass(frozen=True)
class LocalRunContext:
    timezone: str
    local_now: datetime
    local_date: date
    due: bool


@dataclass
class ClaimedDigest:
    digest: ReminderDigest
    occurrences: list[ReminderOccurrence]
    candidates: list[ReminderCandidate]
    created: bool


def local_run_context(now_utc: datetime, timezone_name: str) -> LocalRunContext:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    local_now = now_utc.astimezone(ZoneInfo(timezone_name))
    return LocalRunContext(
        timezone=timezone_name,
        local_now=local_now,
        local_date=local_now.date(),
        due=local_now.timetz().replace(tzinfo=None) >= REMINDER_LOCAL_TIME,
    )


def _enum_value(value) -> str:
    return getattr(value, "value", value) or ""


def list_reminder_candidates(
    db: Session,
    user_id: int,
    local_date: date,
    cadence_offsets: tuple[int, ...],
) -> list[ReminderCandidate]:
    has_subtasks = exists().where(SubTask.task_id == Task.id)
    tasks = (
        db.query(Task)
        .filter(
            Task.user_id == user_id,
            Task.deadline.isnot(None),
            Task.status != "done",
            Task.task_type == TaskType.todo,
            ~has_subtasks,
        )
        .order_by(Task.deadline.asc(), Task.id.asc())
        .all()
    )
    subtasks = (
        db.query(SubTask, Task)
        .join(Task, SubTask.task_id == Task.id)
        .filter(
            Task.user_id == user_id,
            SubTask.notice_time.isnot(None),
            ~SubTask.status.in_(["done", "completed"]),
        )
        .order_by(SubTask.notice_time.asc(), SubTask.id.asc())
        .all()
    )
    deadlines = (
        db.query(Deadline)
        .filter(
            Deadline.user_id == user_id,
            Deadline.status != DeadlineStatus.done,
        )
        .order_by(Deadline.due_date.asc(), Deadline.id.asc())
        .all()
    )

    candidates: list[ReminderCandidate] = []
    for task in tasks:
        task_due = task.deadline.date()
        offset = (task_due - local_date).days
        if offset in cadence_offsets:
            candidates.append(
                ReminderCandidate(
                    item_type="task",
                    item_id=task.id,
                    title=task.title or "未命名任务",
                    description=task.description or "",
                    due_date=task_due,
                    cadence_offset=offset,
                    priority=_enum_value(task.priority) or "medium",
                    subject=task.subject or "",
                    progress=task.progress,
                )
            )
    for subtask, parent in subtasks:
        offset = (subtask.notice_time - local_date).days
        if offset in cadence_offsets:
            candidates.append(
                ReminderCandidate(
                    item_type="subtask",
                    item_id=subtask.id,
                    title=subtask.name or "未命名子任务",
                    description=subtask.description or "",
                    due_date=subtask.notice_time,
                    cadence_offset=offset,
                    priority=subtask.level or "medium",
                    subject=parent.subject or "",
                )
            )
    for deadline in deadlines:
        offset = (deadline.due_date - local_date).days
        if offset in cadence_offsets:
            candidates.append(
                ReminderCandidate(
                    item_type="deadline",
                    item_id=deadline.id,
                    title=deadline.title or "未命名 Deadline",
                    description=deadline.description or "",
                    due_date=deadline.due_date,
                    cadence_offset=offset,
                    priority=_enum_value(deadline.priority) or "medium",
                    subject=deadline.subject or "",
                )
            )
    return sorted(candidates, key=lambda item: (item.due_date, item.item_type, item.item_id))


def _create_or_get_digest(
    db: Session,
    user_id: int,
    local_date: date,
    preferences: ResolvedReminderPreferences,
) -> tuple[ReminderDigest, bool]:
    existing = (
        db.query(ReminderDigest)
        .filter(
            ReminderDigest.user_id == user_id,
            ReminderDigest.local_date == local_date,
        )
        .first()
    )
    if existing:
        return existing, False
    digest = ReminderDigest(
        user_id=user_id,
        local_date=local_date,
        timezone=preferences.timezone,
        language=preferences.language,
        role_card_id=preferences.role_card.id if preferences.role_card else None,
        item_snapshot=[],
        state=ReminderDigestState.preparing,
    )
    db.add(digest)
    try:
        db.commit()
        db.refresh(digest)
        return digest, True
    except IntegrityError:
        # MySQL REPEATABLE READ may retain a snapshot that predates the winning
        # transaction. End the failed transaction before reading the winner.
        db.rollback()
        existing = (
            db.query(ReminderDigest)
            .filter(
                ReminderDigest.user_id == user_id,
                ReminderDigest.local_date == local_date,
            )
            .one()
        )
        return existing, False


def claim_daily_digest(
    db: Session,
    user_id: int,
    now_utc: datetime,
    preferences: ResolvedReminderPreferences,
) -> Optional[ClaimedDigest]:
    context = local_run_context(now_utc, preferences.timezone)
    if not preferences.enabled or not context.due:
        return None

    existing_digest = (
        db.query(ReminderDigest)
        .filter(
            ReminderDigest.user_id == user_id,
            ReminderDigest.local_date == context.local_date,
        )
        .first()
    )
    if existing_digest and existing_digest.state != ReminderDigestState.preparing:
        return ClaimedDigest(existing_digest, [], [], False)

    candidates = list_reminder_candidates(
        db, user_id, context.local_date, preferences.cadence_offsets
    )
    if not candidates:
        return None
    digest, created = _create_or_get_digest(
        db, user_id, context.local_date, preferences
    )
    digest_id = digest.id

    occurrences: list[ReminderOccurrence] = []
    selected: list[ReminderCandidate] = []
    for candidate in candidates:
        occurrence = (
            db.query(ReminderOccurrence)
            .filter(
                ReminderOccurrence.user_id == user_id,
                ReminderOccurrence.item_type == candidate.item_type,
                ReminderOccurrence.item_id == candidate.item_id,
                ReminderOccurrence.due_date == candidate.due_date,
                ReminderOccurrence.cadence_offset == candidate.cadence_offset,
            )
            .first()
        )
        if not occurrence:
            occurrence = ReminderOccurrence(
                user_id=user_id,
                item_type=candidate.item_type,
                item_id=candidate.item_id,
                due_date=candidate.due_date,
                cadence_offset=candidate.cadence_offset,
                local_scheduled_date=context.local_date,
                digest_id=digest_id,
                state=ReminderOccurrenceState.claimed,
            )
            db.add(occurrence)
            try:
                db.commit()
                db.refresh(occurrence)
            except IntegrityError:
                db.rollback()
                occurrence = (
                    db.query(ReminderOccurrence)
                    .filter(
                        ReminderOccurrence.user_id == user_id,
                        ReminderOccurrence.item_type == candidate.item_type,
                        ReminderOccurrence.item_id == candidate.item_id,
                        ReminderOccurrence.due_date == candidate.due_date,
                        ReminderOccurrence.cadence_offset == candidate.cadence_offset,
                    )
                    .one()
                )
        if occurrence.digest_id == digest_id and occurrence.state == ReminderOccurrenceState.claimed:
            occurrences.append(occurrence)
            selected.append(candidate)

    db.commit()
    digest = db.query(ReminderDigest).filter(ReminderDigest.id == digest_id).one()
    if not selected and not created:
        return ClaimedDigest(digest, [], [], False)
    return ClaimedDigest(digest, occurrences, selected, created)


def _reload_candidate(
    db: Session, user_id: int, occurrence: ReminderOccurrence
) -> Optional[ReminderCandidate]:
    if occurrence.item_type == "task":
        task = (
            db.query(Task)
            .filter(Task.id == occurrence.item_id, Task.user_id == user_id)
            .first()
        )
        if (
            not task
            or task.status == "done"
            or not task.deadline
            or task.deadline.date() != occurrence.due_date
            or task.task_type != TaskType.todo
            or db.query(SubTask).filter(SubTask.task_id == task.id).first()
        ):
            return None
        return ReminderCandidate(
            item_type="task",
            item_id=task.id,
            title=task.title or "未命名任务",
            description=task.description or "",
            due_date=task.deadline.date(),
            cadence_offset=occurrence.cadence_offset,
            priority=_enum_value(task.priority) or "medium",
            subject=task.subject or "",
            progress=task.progress,
        )
    if occurrence.item_type == "subtask":
        row = (
            db.query(SubTask, Task)
            .join(Task, SubTask.task_id == Task.id)
            .filter(
                SubTask.id == occurrence.item_id,
                Task.user_id == user_id,
            )
            .first()
        )
        if not row:
            return None
        subtask, parent = row
        if (
            subtask.status in {"done", "completed"}
            or subtask.notice_time != occurrence.due_date
        ):
            return None
        return ReminderCandidate(
            item_type="subtask",
            item_id=subtask.id,
            title=subtask.name or "未命名子任务",
            description=subtask.description or "",
            due_date=subtask.notice_time,
            cadence_offset=occurrence.cadence_offset,
            priority=subtask.level or "medium",
            subject=parent.subject or "",
        )
    if occurrence.item_type == "deadline":
        deadline = (
            db.query(Deadline)
            .filter(Deadline.id == occurrence.item_id, Deadline.user_id == user_id)
            .first()
        )
        if (
            not deadline
            or deadline.status == DeadlineStatus.done
            or deadline.due_date != occurrence.due_date
        ):
            return None
        return ReminderCandidate(
            item_type="deadline",
            item_id=deadline.id,
            title=deadline.title or "未命名 Deadline",
            description=deadline.description or "",
            due_date=deadline.due_date,
            cadence_offset=occurrence.cadence_offset,
            priority=_enum_value(deadline.priority) or "medium",
            subject=deadline.subject or "",
        )
    return None


def finalize_digest_snapshot(db: Session, claimed: ClaimedDigest) -> list[dict]:
    snapshots: list[dict] = []
    for occurrence in claimed.occurrences:
        current = _reload_candidate(db, claimed.digest.user_id, occurrence)
        if not current:
            occurrence.state = ReminderOccurrenceState.cancelled
            occurrence.cancellation_reason = "missing_completed_or_rescheduled"
            continue
        occurrence.state = ReminderOccurrenceState.included
        occurrence.digest_id = claimed.digest.id
        snapshots.append(current.snapshot())

    claimed.digest.item_snapshot = snapshots
    if not snapshots:
        claimed.digest.state = ReminderDigestState.cancelled
    db.commit()
    return snapshots


def revalidate_digest_snapshot(db: Session, digest: ReminderDigest) -> list[dict]:
    occurrences = (
        db.query(ReminderOccurrence)
        .filter(
            ReminderOccurrence.digest_id == digest.id,
            ReminderOccurrence.state.in_(
                [ReminderOccurrenceState.claimed, ReminderOccurrenceState.included]
            ),
        )
        .order_by(ReminderOccurrence.id.asc())
        .all()
    )
    snapshots = []
    for occurrence in occurrences:
        current = _reload_candidate(db, digest.user_id, occurrence)
        if not current:
            occurrence.state = ReminderOccurrenceState.cancelled
            occurrence.cancellation_reason = "missing_completed_or_rescheduled"
            continue
        occurrence.state = ReminderOccurrenceState.included
        snapshots.append(current.snapshot())
    digest.item_snapshot = snapshots
    if not snapshots:
        digest.state = ReminderDigestState.cancelled
    db.commit()
    return snapshots
