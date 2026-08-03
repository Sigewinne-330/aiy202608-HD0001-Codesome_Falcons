from sqlalchemy import Column, DateTime, Index, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from database import Base


class EmailVerification(Base):
    __tablename__ = "email_verifications"
    __table_args__ = (
        Index("ix_email_verifications_email_created", "email", "created_at"),
        Index("ix_email_verifications_ip_created", "request_ip", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(100), nullable=False)
    code_salt = Column(String(64), nullable=False)
    code_digest = Column(String(64), nullable=False)
    registration_token_digest = Column(String(64), unique=True, nullable=True)
    request_ip = Column(String(45), nullable=False, default="unknown")
    delivery_status = Column(String(20), nullable=False, default="pending")
    failed_attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False)
    proof_expires_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

