from sqlalchemy import Column, Integer, String, Text, DateTime, TIMESTAMP, ForeignKey, DECIMAL, Boolean, Enum, JSON
from sqlalchemy.sql import func
from database import Base
import enum


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TaskStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"
    overdue = "overdue"


class TaskType(str, enum.Enum):
    todo = "todo"
    process = "process"


class TaskCategory(str, enum.Enum):
    IA = "IA"
    EE = "EE"
    TOK = "TOK"
    CAS = "CAS"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            normalized = value.upper()
            return cls.__members__.get(normalized)
        return None


class Task(Base):
    """任务表 —— 对应 MySQL 表 `task`（新表体系，已扩展字段）"""
    __tablename__ = "task"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    id_name = Column(String(255), nullable=False, default="")
    task_type = Column(Enum(TaskType), default=TaskType.todo, nullable=False)
    title = Column(String(255), nullable=False)
    deadline = Column(DateTime, default=None)
    # NULL inherits the user's defaults; [] explicitly disables relative reminders.
    reminder_offsets_minutes = Column(JSON, nullable=True, default=None)
    description = Column(Text)
    subject = Column(String(100), default=None)
    # Keep the physical column as VARCHAR for migration compatibility; values
    # are validated through TaskCategory at the application boundary.
    category = Column(String(20), default=None, comment="IA | EE | TOK | CAS")
    priority = Column(String(20), default="medium")
    estimated_hours = Column(DECIMAL(5, 1), default=0)
    progress = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    status = Column(String(50), default="todo", comment="任务状态")
    personal_deadline = Column(DateTime, default=None)
    update_time = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
