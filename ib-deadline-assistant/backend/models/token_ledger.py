from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from database import Base


class TokenLedger(Base):
    """积分流水表 —— 每笔消耗/充值/赠送都留痕"""
    __tablename__ = "token_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    change_type = Column(String(20), nullable=False, comment="consume / recharge / gift")
    change_amount = Column(Integer, nullable=False, comment="变动积分（消耗为负）")
    balance_after = Column(Integer, nullable=False, comment="变动后余额")
    ref_id = Column(Integer, default=None, comment="关联 chat_message / billing_orders id")
    ref_type = Column(String(20), default=None, comment="chat / order / register")
    note = Column(String(255), default=None)
    created_at = Column(TIMESTAMP, server_default=func.now(), index=True)
