from sqlalchemy import Boolean, Column, Integer, String, TIMESTAMP, text
from sqlalchemy.sql import func
from database import Base


class AppUser(Base):
    """用户表 —— 对应 MySQL 表 `user`"""
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    nickname = Column(String(100), default=None)
    password = Column(String(255), nullable=False)
    grade = Column(String(50), default=None, comment="用户等级/年级")
    register_time = Column(TIMESTAMP, server_default=func.now())
    update_time = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    email = Column(String(100), unique=True, default=None)
    phone_number = Column(String(20), default=None)
    wechat_id = Column(String(50), default=None)
    balance = Column(Integer, default=0, comment="积分余额（1 积分 = 1000 token）")
    is_admin = Column(Boolean, nullable=False, default=False, server_default=text("0"))
