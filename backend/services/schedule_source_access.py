"""Owner-scoped lookup for the three authoritative scheduling source types."""

from typing import Optional

from sqlalchemy.orm import Session

from models.deadline import Deadline
from models.sub_task import SubTask
from models.task_new import Task


def owned_schedule_source(
    db: Session,
    user_id: int,
    source_type: str,
    source_id: int,
    *,
    lock: bool = False,
) -> Optional[object]:
    if source_type == "task":
        query = db.query(Task).filter(Task.id == source_id, Task.user_id == user_id)
    elif source_type == "subtask":
        query = (
            db.query(SubTask)
            .join(Task, SubTask.task_id == Task.id)
            .filter(SubTask.id == source_id, Task.user_id == user_id)
        )
    elif source_type == "deadline":
        query = db.query(Deadline).filter(Deadline.id == source_id, Deadline.user_id == user_id)
    else:
        return None
    if lock:
        query = query.with_for_update()
    return query.first()
