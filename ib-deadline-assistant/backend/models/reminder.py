import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import func

from database import Base


class ReminderOccurrenceState(str, enum.Enum):
    claimed = "claimed"
    included = "included"
    cancelled = "cancelled"


class ReminderDigestState(str, enum.Enum):
    preparing = "preparing"
    ready = "ready"
    cancelled = "cancelled"


class ReminderGenerationMode(str, enum.Enum):
    llm = "llm"
    template = "template"


class ReminderDeliveryStatus(str, enum.Enum):
    pending = "pending"
    attempting = "attempting"
    delivered = "delivered"
    retryable = "retryable"
    failed = "failed"
    skipped = "skipped"


class LLMUsageOutcome(str, enum.Enum):
    succeeded = "succeeded"
    failed = "failed"


class ReminderRoleCard(Base):
    __tablename__ = "reminder_role_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(80), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="")
    personality = Column(Text, nullable=False, default="")
    speaking_style = Column(Text, nullable=False, default="")
    system_prompt = Column(Text, nullable=False, default="")
    example_messages = Column(JSON, nullable=False, default=list)
    extensions = Column(JSON, nullable=False, default=dict)
    scope = Column(
        String(20), nullable=False, default="global", server_default=text("'global'")
    )
    owner_user_id = Column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    created_by_user_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    creator = Column(String(120), nullable=False, default="IB Deadline Assistant")
    version = Column(String(30), nullable=False, default="1.0")
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    is_builtin = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReminderPreference(Base):
    __tablename__ = "reminder_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    language = Column(String(35), nullable=False, default="zh-CN")
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai")
    cadence_offsets = Column(JSON, nullable=False, default=lambda: [2, 1, 0, -1, -3, -7])
    email_enabled = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    chat_enabled = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    role_card_id = Column(
        Integer, ForeignKey("reminder_role_cards.id", ondelete="SET NULL"), nullable=True
    )
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReminderOccurrence(Base):
    __tablename__ = "reminder_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "item_type",
            "item_id",
            "due_date",
            "cadence_offset",
            name="uq_reminder_occurrence_identity",
        ),
        Index("ix_reminder_occurrence_user_date", "user_id", "local_scheduled_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    item_type = Column(String(20), nullable=False)
    item_id = Column(Integer, nullable=False)
    due_date = Column(Date, nullable=False)
    cadence_offset = Column(Integer, nullable=False)
    local_scheduled_date = Column(Date, nullable=False)
    state = Column(
        Enum(ReminderOccurrenceState),
        nullable=False,
        default=ReminderOccurrenceState.claimed,
    )
    cancellation_reason = Column(String(80), nullable=True)
    digest_id = Column(
        Integer, ForeignKey("reminder_digests.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReminderDigest(Base):
    __tablename__ = "reminder_digests"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_reminder_digest_user_day"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    local_date = Column(Date, nullable=False)
    timezone = Column(String(64), nullable=False)
    language = Column(String(35), nullable=False)
    role_card_id = Column(
        Integer, ForeignKey("reminder_role_cards.id", ondelete="SET NULL"), nullable=True
    )
    subject = Column(String(255), nullable=True)
    framing_text = Column(Text, nullable=True)
    item_snapshot = Column(JSON, nullable=False, default=list)
    body_text = Column(Text, nullable=True)
    chat_url = Column(String(1000), nullable=True)
    generation_mode = Column(Enum(ReminderGenerationMode), nullable=True)
    generation_attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    state = Column(
        Enum(ReminderDigestState),
        nullable=False,
        default=ReminderDigestState.preparing,
    )
    chat_message_id = Column(
        Integer, ForeignKey("chat_message.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"
    __table_args__ = (
        UniqueConstraint("digest_id", "channel", name="uq_reminder_delivery_channel"),
        Index("ix_reminder_delivery_retry", "status", "next_attempt_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    digest_id = Column(
        Integer, ForeignKey("reminder_digests.id", ondelete="CASCADE"), nullable=False
    )
    channel = Column(String(40), nullable=False)
    status = Column(
        Enum(ReminderDeliveryStatus),
        nullable=False,
        default=ReminderDeliveryStatus.pending,
    )
    attempt_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    attempt_token = Column(String(64), nullable=True)
    attempt_started_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(80), nullable=True)
    provider_message_id = Column(String(255), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class LLMUsageRecord(Base):
    __tablename__ = "llm_usage_records"
    __table_args__ = (
        Index("ix_llm_usage_user_created", "user_id", "created_at"),
        Index("ix_llm_usage_purpose_created", "purpose", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    purpose = Column(String(40), nullable=False)
    provider = Column(String(80), nullable=True)
    model = Column(String(160), nullable=True)
    correlation_id = Column(String(100), nullable=False)
    reminder_digest_id = Column(
        Integer, ForeignKey("reminder_digests.id", ondelete="SET NULL"), nullable=True
    )
    chat_message_id = Column(
        Integer, ForeignKey("chat_message.id", ondelete="SET NULL"), nullable=True
    )
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    outcome = Column(Enum(LLMUsageOutcome), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
