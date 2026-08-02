from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.sql import func
from database import Base


class ChatMessage(Base):
    """聊天消息表"""
    __tablename__ = "chat_message"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    role = Column(String(20), nullable=False, comment="user / assistant / system")
    extra = Column(JSON, default=None, comment="扩展字段")
    token = Column(Integer, default=0, comment="token 消耗数")
    update_time = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
