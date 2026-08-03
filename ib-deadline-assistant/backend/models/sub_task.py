from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, Enum, TIMESTAMP
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
