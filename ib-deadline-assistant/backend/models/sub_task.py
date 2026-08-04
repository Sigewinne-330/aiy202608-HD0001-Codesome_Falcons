from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, Enum, TIMESTAMP, DECIMAL, Boolean
from sqlalchemy.sql import func
from database import Base


class SubTask(Base):
    __tablename__ = "sub_task"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("task.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    notice_time = Column(Date, default=None, comment="截止/提醒日期")
    level = Column(String(20), default="medium", comment="优先级")
    status = Column(String(50), default="pending", comment="状态")
    notice_method = Column(String(100), default=None, comment="提醒方式")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    estimated_hours = Column(DECIMAL(5, 1), nullable=False, default=0)
    earliest_start_date = Column(Date, nullable=True)
    hard_deadline_date = Column(Date, nullable=True)
    energy_intensity = Column(DECIMAL(3, 2), nullable=False, default=1.0)
    effort_source = Column(String(20), nullable=False, default="default")
    is_schedule_locked = Column(Boolean, nullable=False, default=False)
    schedule_version = Column(Integer, nullable=False, default=1)
    deferral_count = Column(Integer, nullable=False, default=0)
    schedule_kind = Column(String(50), nullable=True)
