from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.reminder import (
    ReminderDelivery,
    ReminderDeliveryStatus,
    ReminderDigest,
    TaskReminderDelivery,
    TaskReminderNotification,
)
from models.user import User
from services.reminder_channels import ChannelRegistry, ReminderEnvelope
from services.reminder_preferences import ResolvedReminderPreferences


MAX_DELIVERY_ATTEMPTS = 3
ATTEMPT_LEASE_SECONDS = 15 * 60


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_envelope(digest: ReminderDigest, user: User) -> ReminderEnvelope:
    references = tuple(
        {
            "item_type": item.get("item_type"),
            "item_id": item.get("item_id"),
            "due_date": item.get("due_date"),
        }
        for item in (digest.item_snapshot or [])
    )
    return ReminderEnvelope(
        digest_id=digest.id,
        task_notification_id=None,
        user_id=digest.user_id,
        recipient=user.email,
        subject=digest.subject or "Schedule reminder",
        body=digest.body_text or "",
        role_card_id=digest.role_card_id,
        item_references=references,
    )


def build_task_reminder_envelope(
    notification: TaskReminderNotification, user: User
) -> ReminderEnvelope:
    return ReminderEnvelope(
        digest_id=None,
        task_notification_id=notification.id,
        user_id=notification.user_id,
        recipient=user.email,
        subject=notification.subject,
        body=notification.body_text,
        role_card_id=None,
        item_references=(
            {
                "item_type": "task",
                "item_id": notification.task_id,
                "due_at": notification.deadline_at.isoformat(),
                "offset_minutes": notification.offset_minutes,
            },
        ),
    )


def get_or_create_delivery(
    db: Session, digest_id: int, channel_name: str
) -> ReminderDelivery:
    existing = (
        db.query(ReminderDelivery)
        .filter(
            ReminderDelivery.digest_id == digest_id,
            ReminderDelivery.channel == channel_name,
        )
        .first()
    )
    if existing:
        return existing
    row = ReminderDelivery(digest_id=digest_id, channel=channel_name)
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        # End a failed MySQL REPEATABLE READ transaction before reading the
        # delivery row committed by the winning worker.
        db.rollback()
        return (
            db.query(ReminderDelivery)
            .filter(
                ReminderDelivery.digest_id == digest_id,
                ReminderDelivery.channel == channel_name,
            )
            .one()
        )


def _mark_skipped(db: Session, delivery: ReminderDelivery) -> None:
    delivery.status = ReminderDeliveryStatus.skipped
    delivery.last_error_code = "channel_disabled"
    db.commit()


def _fresh_attempt(delivery: ReminderDelivery, current: datetime) -> bool:
    return bool(
        delivery.attempt_started_at
        and delivery.attempt_started_at
        > current - timedelta(seconds=ATTEMPT_LEASE_SECONDS)
    )


def _claim_attempt(
    db: Session,
    delivery: ReminderDelivery,
    *,
    current: datetime,
    allow_stale_attempt: bool,
) -> tuple[ReminderDelivery, str | None]:
    token = uuid4().hex
    eligible = [
        ReminderDelivery.status == ReminderDeliveryStatus.pending,
        and_(
            ReminderDelivery.status == ReminderDeliveryStatus.retryable,
            or_(
                ReminderDelivery.next_attempt_at.is_(None),
                ReminderDelivery.next_attempt_at <= current,
            ),
        ),
    ]
    if allow_stale_attempt:
        eligible.append(
            and_(
                ReminderDelivery.status == ReminderDeliveryStatus.attempting,
                or_(
                    ReminderDelivery.attempt_started_at.is_(None),
                    ReminderDelivery.attempt_started_at
                    <= current - timedelta(seconds=ATTEMPT_LEASE_SECONDS),
                ),
            )
        )

    claimed = (
        db.query(ReminderDelivery)
        .filter(
            ReminderDelivery.id == delivery.id,
            ReminderDelivery.attempt_count < MAX_DELIVERY_ATTEMPTS,
            or_(*eligible),
        )
        .update(
            {
                ReminderDelivery.attempt_count: ReminderDelivery.attempt_count + 1,
                ReminderDelivery.status: ReminderDeliveryStatus.attempting,
                ReminderDelivery.attempt_token: token,
                ReminderDelivery.attempt_started_at: current,
                ReminderDelivery.next_attempt_at: None,
            },
            synchronize_session=False,
        )
    )
    delivery_id = delivery.id
    db.commit()
    row = db.query(ReminderDelivery).filter(ReminderDelivery.id == delivery_id).one()
    return row, token if claimed == 1 and row.attempt_token == token else None


def deliver_one_channel(
    db: Session,
    *,
    digest: ReminderDigest,
    user: User,
    channel_name: str,
    enabled: bool,
    registry: ChannelRegistry,
    now: datetime | None = None,
) -> ReminderDelivery:
    current = now or utcnow_naive()
    delivery = get_or_create_delivery(db, digest.id, channel_name)
    if not enabled:
        if delivery.status not in {
            ReminderDeliveryStatus.delivered,
            ReminderDeliveryStatus.skipped,
        }:
            _mark_skipped(db, delivery)
        return delivery
    if delivery.status in {
        ReminderDeliveryStatus.delivered,
        ReminderDeliveryStatus.skipped,
        ReminderDeliveryStatus.failed,
    }:
        return delivery
    channel = registry.get(channel_name)
    if delivery.status == ReminderDeliveryStatus.attempting:
        if _fresh_attempt(delivery, current):
            return delivery
        if channel.ambiguous_external_side_effect:
            updated = (
                db.query(ReminderDelivery)
                .filter(
                    ReminderDelivery.id == delivery.id,
                    ReminderDelivery.status == ReminderDeliveryStatus.attempting,
                    or_(
                        ReminderDelivery.attempt_started_at.is_(None),
                        ReminderDelivery.attempt_started_at
                        <= current - timedelta(seconds=ATTEMPT_LEASE_SECONDS),
                    ),
                )
                .update(
                    {
                        ReminderDelivery.status: ReminderDeliveryStatus.failed,
                        ReminderDelivery.last_error_code: "delivery_outcome_unknown",
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            db.refresh(delivery)
            if updated:
                return delivery
            return delivery
    if (
        delivery.status == ReminderDeliveryStatus.retryable
        and delivery.next_attempt_at
        and delivery.next_attempt_at > current
    ):
        return delivery
    if delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS:
        delivery.status = ReminderDeliveryStatus.failed
        delivery.last_error_code = delivery.last_error_code or "retry_exhausted"
        db.commit()
        return delivery

    delivery, attempt_token = _claim_attempt(
        db,
        delivery,
        current=current,
        allow_stale_attempt=not channel.ambiguous_external_side_effect,
    )
    if not attempt_token:
        if delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS and delivery.status not in {
            ReminderDeliveryStatus.delivered,
            ReminderDeliveryStatus.failed,
            ReminderDeliveryStatus.skipped,
        }:
            delivery.status = ReminderDeliveryStatus.failed
            delivery.last_error_code = delivery.last_error_code or "retry_exhausted"
            db.commit()
        return delivery

    delivery_id = delivery.id
    try:
        result = channel.deliver(db, build_envelope(digest, user))
    except Exception:
        # Keep channel failures isolated. Roll back any partial database work,
        # then update only the lease still owned by this attempt.
        db.rollback()
        delivery = (
            db.query(ReminderDelivery)
            .filter(
                ReminderDelivery.id == delivery_id,
                ReminderDelivery.status == ReminderDeliveryStatus.attempting,
                ReminderDelivery.attempt_token == attempt_token,
            )
            .one_or_none()
        )
        if delivery is None:
            return (
                db.query(ReminderDelivery)
                .filter(ReminderDelivery.id == delivery_id)
                .one()
            )
        delivery.attempt_token = None
        if channel.ambiguous_external_side_effect:
            delivery.status = ReminderDeliveryStatus.failed
            delivery.last_error_code = "delivery_outcome_unknown"
        elif delivery.attempt_count < MAX_DELIVERY_ATTEMPTS:
            delivery.status = ReminderDeliveryStatus.retryable
            delivery.last_error_code = "channel_persistence_failed"
            delivery.next_attempt_at = current + timedelta(
                seconds=60 * (2 ** (delivery.attempt_count - 1))
            )
        else:
            delivery.status = ReminderDeliveryStatus.failed
            delivery.last_error_code = "channel_persistence_failed"
        db.commit()
        db.refresh(delivery)
        return delivery

    delivery = (
        db.query(ReminderDelivery)
        .filter(
            ReminderDelivery.id == delivery_id,
            ReminderDelivery.status == ReminderDeliveryStatus.attempting,
            ReminderDelivery.attempt_token == attempt_token,
        )
        .one_or_none()
    )
    if delivery is None:
        return db.query(ReminderDelivery).filter(ReminderDelivery.id == delivery_id).one()
    delivery.provider_message_id = result.provider_message_id
    delivery.last_error_code = result.error_code
    delivery.attempt_token = None
    if result.status == "delivered":
        delivery.status = ReminderDeliveryStatus.delivered
        delivery.delivered_at = current
    elif result.status == "retryable" and delivery.attempt_count < MAX_DELIVERY_ATTEMPTS:
        delivery.status = ReminderDeliveryStatus.retryable
        delivery.next_attempt_at = current + timedelta(
            seconds=60 * (2 ** (delivery.attempt_count - 1))
        )
    else:
        delivery.status = ReminderDeliveryStatus.failed
        delivery.last_error_code = result.error_code or "delivery_failed"
    db.commit()
    db.refresh(delivery)
    return delivery


def deliver_digest_channels(
    db: Session,
    *,
    digest: ReminderDigest,
    user: User,
    preferences: ResolvedReminderPreferences,
    registry: ChannelRegistry,
    now: datetime | None = None,
) -> dict[str, ReminderDelivery]:
    outcomes = {}
    for channel_name, enabled in (
        ("chat", preferences.chat_enabled),
        ("email", preferences.email_enabled),
    ):
        outcomes[channel_name] = deliver_one_channel(
            db,
            digest=digest,
            user=user,
            channel_name=channel_name,
            enabled=enabled,
            registry=registry,
            now=now,
        )
    return outcomes


def get_or_create_task_delivery(
    db: Session, notification_id: int, channel_name: str
) -> TaskReminderDelivery:
    existing = (
        db.query(TaskReminderDelivery)
        .filter(
            TaskReminderDelivery.notification_id == notification_id,
            TaskReminderDelivery.channel == channel_name,
        )
        .first()
    )
    if existing:
        return existing
    row = TaskReminderDelivery(notification_id=notification_id, channel=channel_name)
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        return (
            db.query(TaskReminderDelivery)
            .filter(
                TaskReminderDelivery.notification_id == notification_id,
                TaskReminderDelivery.channel == channel_name,
            )
            .one()
        )


def deliver_task_reminder_one_channel(
    db: Session,
    *,
    notification: TaskReminderNotification,
    user: User,
    channel_name: str,
    enabled: bool,
    registry: ChannelRegistry,
    now: datetime | None = None,
) -> TaskReminderDelivery:
    """Task-relative equivalent of the digest delivery state machine."""
    current = now or utcnow_naive()
    delivery = get_or_create_task_delivery(db, notification.id, channel_name)
    if not enabled:
        if delivery.status not in {ReminderDeliveryStatus.delivered, ReminderDeliveryStatus.skipped}:
            delivery.status = ReminderDeliveryStatus.skipped
            delivery.last_error_code = "channel_disabled"
            db.commit()
        return delivery
    if delivery.status in {ReminderDeliveryStatus.delivered, ReminderDeliveryStatus.skipped, ReminderDeliveryStatus.failed}:
        return delivery
    channel = registry.get(channel_name)
    if delivery.status == ReminderDeliveryStatus.attempting and _fresh_attempt(delivery, current):
        return delivery
    if delivery.status == ReminderDeliveryStatus.attempting and channel.ambiguous_external_side_effect:
        delivery.status = ReminderDeliveryStatus.failed
        delivery.last_error_code = "delivery_outcome_unknown"
        db.commit()
        return delivery
    if delivery.status == ReminderDeliveryStatus.retryable and delivery.next_attempt_at and delivery.next_attempt_at > current:
        return delivery
    if delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS:
        delivery.status = ReminderDeliveryStatus.failed
        delivery.last_error_code = delivery.last_error_code or "retry_exhausted"
        db.commit()
        return delivery

    token = uuid4().hex
    claimed = (
        db.query(TaskReminderDelivery)
        .filter(
            TaskReminderDelivery.id == delivery.id,
            TaskReminderDelivery.attempt_count < MAX_DELIVERY_ATTEMPTS,
            TaskReminderDelivery.status.in_([
                ReminderDeliveryStatus.pending,
                ReminderDeliveryStatus.retryable,
                ReminderDeliveryStatus.attempting,
            ]),
        )
        .update(
            {
                TaskReminderDelivery.attempt_count: TaskReminderDelivery.attempt_count + 1,
                TaskReminderDelivery.status: ReminderDeliveryStatus.attempting,
                TaskReminderDelivery.attempt_token: token,
                TaskReminderDelivery.attempt_started_at: current,
                TaskReminderDelivery.next_attempt_at: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    delivery = db.query(TaskReminderDelivery).filter(TaskReminderDelivery.id == delivery.id).one()
    if claimed != 1 or delivery.attempt_token != token:
        return delivery
    try:
        result = channel.deliver(db, build_task_reminder_envelope(notification, user))
    except Exception:
        db.rollback()
        result = None
    delivery = db.query(TaskReminderDelivery).filter(TaskReminderDelivery.id == delivery.id).one()
    if delivery.attempt_token != token:
        return delivery
    delivery.attempt_token = None
    if result is not None and result.status == "delivered":
        delivery.status = ReminderDeliveryStatus.delivered
        delivery.provider_message_id = result.provider_message_id
        delivery.last_error_code = result.error_code
        delivery.delivered_at = current
    elif result is not None and result.status == "retryable" and delivery.attempt_count < MAX_DELIVERY_ATTEMPTS:
        delivery.status = ReminderDeliveryStatus.retryable
        delivery.last_error_code = result.error_code
        delivery.next_attempt_at = current + timedelta(seconds=60 * (2 ** (delivery.attempt_count - 1)))
    else:
        delivery.status = ReminderDeliveryStatus.failed if channel.ambiguous_external_side_effect else ReminderDeliveryStatus.retryable
        delivery.last_error_code = (result.error_code if result else "channel_persistence_failed") or "delivery_failed"
        if delivery.status == ReminderDeliveryStatus.retryable:
            delivery.next_attempt_at = current + timedelta(seconds=60 * (2 ** (delivery.attempt_count - 1)))
    db.commit()
    db.refresh(delivery)
    return delivery


def deliver_task_reminder_channels(
    db: Session,
    *,
    notification: TaskReminderNotification,
    user: User,
    preferences: ResolvedReminderPreferences,
    registry: ChannelRegistry,
    now: datetime | None = None,
) -> dict[str, TaskReminderDelivery]:
    return {
        name: deliver_task_reminder_one_channel(
            db, notification=notification, user=user, channel_name=name,
            enabled=enabled, registry=registry, now=now,
        )
        for name, enabled in (("chat", preferences.chat_enabled), ("email", preferences.email_enabled))
    }
