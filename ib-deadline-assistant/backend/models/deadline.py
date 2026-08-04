import enum
from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Enum, TIMESTAMP, DECIMAL, Boolean
from sqlalchemy.sql import func
from database import Base
from .task_new import Priority


class DeadlineStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    overdue = "overdue"


class Deadline(Base):
    __tablename__ = "deadlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(100))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    due_date = Column(Date, nullable=False)
    subject = Column(String(100))
    priority = Column(Enum(Priority), default=Priority.medium)
    status = Column(Enum(DeadlineStatus), default=DeadlineStatus.pending)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    estimated_hours = Column(DECIMAL(5, 1), nullable=True)
    energy_intensity = Column(DECIMAL(3, 2), nullable=False, default=1.0)
    effort_source = Column(String(20), nullable=False, default="default")
    is_schedule_locked = Column(Boolean, nullable=False, default=True)
    schedule_version = Column(Integer, nullable=False, default=1)
    schedule_kind = Column(String(50), nullable=True)
