from sqlalchemy import Column, Integer, String, Text, DateTime, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from database import Base


class Task(Base):
    """任务表"""
    __tablename__ = "task"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    id_name = Column(String(255), nullable=False, comment="任务标识/名称")
    deadline = Column(DateTime, default=None)
    description = Column(Text)
    status = Column(String(50), default="pending", comment="任务状态")
    personal_deadline = Column(DateTime, default=None, comment="个人截止时间")
    update_time = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
