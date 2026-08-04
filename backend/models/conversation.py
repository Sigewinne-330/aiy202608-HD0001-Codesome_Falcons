from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from database import Base


class Conversation(Base):
    """会话表"""
    __tablename__ = "conversation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), default=None)
    update_time = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
