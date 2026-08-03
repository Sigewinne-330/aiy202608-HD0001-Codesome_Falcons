import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from models.reminder import LLMUsageOutcome, LLMUsageRecord


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_llm_usage(
    db: Session,
    *,
    user_id: int,
    purpose: str,
    provider: Optional[str],
    model: Optional[str],
    outcome: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    reminder_digest_id: Optional[int] = None,
    chat_message_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
) -> LLMUsageRecord:
    row = LLMUsageRecord(
        user_id=user_id,
        purpose=purpose,
        provider=provider,
        model=model,
        correlation_id=correlation_id or uuid.uuid4().hex,
        reminder_digest_id=reminder_digest_id,
        chat_message_id=chat_message_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        outcome=LLMUsageOutcome(outcome),
    )
    db.add(row)
    db.flush()
    return row


def monthly_token_usage(db: Session, user_id: int, now: Optional[datetime] = None) -> int:
    current = now or utcnow_naive()
    month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    value = (
        db.query(func.coalesce(func.sum(LLMUsageRecord.total_tokens), 0))
        .filter(
            LLMUsageRecord.user_id == user_id,
            LLMUsageRecord.created_at >= month_start,
            LLMUsageRecord.outcome == LLMUsageOutcome.succeeded,
        )
        .scalar()
    )
    return int(value or 0)


class LLMQuotaPolicy:
    def __init__(self, monthly_limit: Optional[int] = None):
        self.monthly_limit = (
            settings.LLM_MONTHLY_TOKEN_QUOTA if monthly_limit is None else monthly_limit
        )

    def allows_generation(self, db: Session, user_id: int) -> bool:
        if self.monthly_limit <= 0:
            return True
        return monthly_token_usage(db, user_id) < self.monthly_limit
