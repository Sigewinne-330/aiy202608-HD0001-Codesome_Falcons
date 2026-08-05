from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from sqlalchemy.orm import Session

from models.chat_message_new import ChatMessage
from models.conversation import Conversation
from models.reminder import ReminderDigest, TaskReminderNotification
from services.email_service import (
    EmailDeliveryError,
    EmailTransport,
    GenericEmailMessage,
)
from services.email_templates import render_reminder


@dataclass(frozen=True)
class ReminderEnvelope:
    digest_id: Optional[int]
    task_notification_id: Optional[int]
    user_id: int
    recipient: str
    subject: str
    body: str
    role_card_id: Optional[int]
    item_references: tuple[dict, ...]


@dataclass(frozen=True)
class ChannelResult:
    status: str
    error_code: Optional[str] = None
    provider_message_id: Optional[str] = None


class ReminderChannel(Protocol):
    name: str
    ambiguous_external_side_effect: bool

    def deliver(self, db: Session, envelope: ReminderEnvelope) -> ChannelResult: ...


class ChatReminderChannel:
    name = "chat"
    ambiguous_external_side_effect = False

    def deliver(self, db: Session, envelope: ReminderEnvelope) -> ChannelResult:
        source = "demo_reminder" if envelope.digest_id is None else "reminder"
        extra = {"source": source, "digest_id": envelope.digest_id}
        if envelope.task_notification_id is not None:
            notification = (
                db.query(TaskReminderNotification)
                .filter(TaskReminderNotification.id == envelope.task_notification_id)
                .one()
            )
            existing_id = notification.chat_message_id
            source = "task_relative_reminder"
            extra = {
                "source": source,
                "task_reminder_notification_id": notification.id,
                "task_id": notification.task_id,
                "offset_minutes": notification.offset_minutes,
            }
        else:
            digest = None
            existing_id = None
            if envelope.digest_id is not None:
                digest = (
                    db.query(ReminderDigest)
                    .filter(ReminderDigest.id == envelope.digest_id)
                    .one()
                )
                existing_id = digest.chat_message_id
        if existing_id:
            existing = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.id == existing_id,
                    ChatMessage.user_id == envelope.user_id,
                )
                .first()
            )
            if existing:
                return ChannelResult(status="delivered", provider_message_id=str(existing.id))

        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.user_id == envelope.user_id,
                Conversation.title == "日程提醒",
            )
            .order_by(Conversation.id.asc())
            .first()
        )
        if not conversation:
            conversation = Conversation(user_id=envelope.user_id, title="日程提醒")
            db.add(conversation)
            db.flush()

        message = ChatMessage(
            user_id=envelope.user_id,
            conversation_id=conversation.id,
            role="assistant",
            content=envelope.body,
            extra={
                "role_card_id": envelope.role_card_id,
                "items": list(envelope.item_references),
                **extra,
            },
        )
        db.add(message)
        db.flush()
        conversation.update_time = message.update_time
        if envelope.task_notification_id is not None:
            notification.chat_message_id = message.id
        elif digest is not None:
            digest.chat_message_id = message.id
        return ChannelResult(status="delivered", provider_message_id=str(message.id))


def _envelope_has_overdue(envelope: ReminderEnvelope) -> bool:
    """根据 item_references 里的截止时间判断是否含已逾期事项。"""
    now = datetime.now()
    for item in envelope.item_references:
        raw = item.get("due_at") or item.get("due_date")
        if not raw:
            continue
        try:
            due = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if due < now:
            return True
    return False


class EmailReminderChannel:
    name = "email"
    ambiguous_external_side_effect = True

    def __init__(self, transport: EmailTransport):
        self.transport = transport

    def deliver(self, db: Session, envelope: ReminderEnvelope) -> ChannelResult:
        try:
            provider_id = self.transport.send_message(
                GenericEmailMessage(
                    recipient=envelope.recipient,
                    subject=envelope.subject,
                    body=envelope.body,
                    html_body=render_reminder(
                        envelope.subject,
                        envelope.body,
                        overdue=_envelope_has_overdue(envelope),
                    ),
                )
            )
            return ChannelResult(
                status="delivered", provider_message_id=provider_id
            )
        except EmailDeliveryError as exc:
            return ChannelResult(
                status="retryable" if exc.retryable else "failed",
                error_code=exc.code,
            )
        except (OSError, TimeoutError):
            return ChannelResult(status="retryable", error_code="transport_timeout")


class ChannelRegistry:
    def __init__(self, channels: list[ReminderChannel]):
        self._channels = {channel.name: channel for channel in channels}

    def get(self, name: str) -> ReminderChannel:
        if name not in self._channels:
            raise ValueError(f"未注册提醒通道: {name}")
        return self._channels[name]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._channels)
