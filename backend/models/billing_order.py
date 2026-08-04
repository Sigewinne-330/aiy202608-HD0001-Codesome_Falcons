from sqlalchemy import Column, Integer, String, Float, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from database import Base


class BillingOrder(Base):
    """充值订单表"""
    __tablename__ = "billing_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_code = Column(String(20), nullable=False, comment="档位标识 p6/p30/p68/p128")
    amount = Column(Float, nullable=False, comment="支付金额（元）")
    credits = Column(Integer, nullable=False, comment="到账积分")
    status = Column(String(20), nullable=False, default="pending", comment="pending / paid")
    created_at = Column(TIMESTAMP, server_default=func.now())
    paid_at = Column(TIMESTAMP, default=None, nullable=True)
