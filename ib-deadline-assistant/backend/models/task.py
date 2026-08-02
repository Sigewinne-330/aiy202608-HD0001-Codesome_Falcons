from sqlalchemy import Column, Integer, String, Text, Date, DECIMAL, ForeignKey, Enum, TIMESTAMP
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


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"), default=None)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    subject = Column(String(100))
    priority = Column(Enum(Priority), default=Priority.medium)
    status = Column(Enum(TaskStatus), default=TaskStatus.todo)
    deadline = Column(Date)
    estimated_hours = Column(DECIMAL(5, 1), default=0)
    progress = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
