from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from models.reminder import (
    ReminderDelivery,
    ReminderDeliveryStatus,
    ReminderDigest,
    ReminderDigestState,
    ReminderGenerationMode,
    TaskReminderDelivery,
    TaskReminderNotification,
    TaskReminderState,
)
from models.user import User
from services.email_service import EmailTransport, get_email_transport
from services.reminder_agent import (
    ReminderTextAgent,
    deterministic_fallback,
    render_digest_body,
    validated_chat_url,
)
from services.reminder_channels import (
    ChannelResult,
    ChannelRegistry,
    ChatReminderChannel,
    EmailReminderChannel,
    ReminderEnvelope,
)
from services.reminder_delivery import (
    deliver_digest_channels,
    deliver_one_channel,
    deliver_task_reminder_channels,
    deliver_task_reminder_one_channel,
)
from services.reminder_preferences import resolve_preferences
from services.reminder_scheduler import (
    claim_daily_digest,
    claim_due_task_relative_notifications,
    finalize_digest_snapshot,
    list_reminder_candidates,
    local_run_context,
    revalidate_digest_snapshot,
    revalidate_task_relative_notification,
)


@dataclass(frozen=True)
class ReminderRunSummary:
    evaluated_users: int
    due_users: int
    candidate_items: int
    generated_digests: int
    delivered_channels: int
    failed_channels: int
    dry_run: bool


class ReminderOrchestrator:
    def __init__(
        self,
        *,
        agent: Optional[ReminderTextAgent] = None,
        email_transport: Optional[EmailTransport] = None,
    ):
        self.agent = agent or ReminderTextAgent()
        transport = email_transport or get_email_transport()
        self.registry = ChannelRegistry(
            [ChatReminderChannel(), EmailReminderChannel(transport)]
        )

    async def send_demo(self, db: Session, *, user: User) -> dict[str, object]:
        """Send one immediate, non-durable reminder for a local/demo walkthrough."""
        preferences = resolve_preferences(db, user.id)
        now = datetime.now(timezone.utc)
        due_label = now.astimezone(timezone.utc).date().isoformat()
        item_snapshots = [
            {
                "item_type": "demo",
                "item_id": None,
                "title": (
                    "演示提醒"
                    if preferences.language.lower().startswith("zh")
                    else "Demo reminder"
                ),
                "description": "This is a temporary reminder walkthrough.",
                "due_date": due_label,
                "cadence_label": "DEMO",
                "priority": "medium",
            }
        ]
        content = await self.agent.generate(
            db,
            user_id=user.id,
            digest_id=None,
            language=preferences.language,
            role_card=preferences.role_card,
            item_snapshots=item_snapshots,
            app_base_url=settings.APP_BASE_URL,
        )
        envelope = ReminderEnvelope(
            digest_id=None,
            task_notification_id=None,
            user_id=user.id,
            recipient=user.email,
            subject=content.subject,
            body=content.body,
            role_card_id=preferences.role_card.id if preferences.role_card else None,
            item_references=tuple(item_snapshots),
        )
        outcomes: dict[str, ChannelResult] = {}
        for channel_name, enabled in (
            ("chat", preferences.chat_enabled),
            ("email", preferences.email_enabled),
        ):
            if not enabled:
                outcomes[channel_name] = ChannelResult(
                    status="skipped", error_code="channel_disabled"
                )
                continue
            try:
                result = self.registry.get(channel_name).deliver(db, envelope)
                db.commit()
            except Exception:
                db.rollback()
                result = ChannelResult(status="failed", error_code="channel_failed")
            outcomes[channel_name] = result
        return {"subject": content.subject, "outcomes": outcomes}

    async def run(
        self,
        db: Session,
        *,
        now_utc: Optional[datetime] = None,
        only_user_id: Optional[int] = None,
        deliver: bool = True,
    ) -> ReminderRunSummary:
        now = now_utc or datetime.now(timezone.utc)
        query = db.query(User)
        if only_user_id is not None:
            query = query.filter(User.id == only_user_id)
        users = query.order_by(User.id.asc()).all()
        due_users = candidate_items = generated = delivered = failed = 0

        if deliver:
            retry_rows = (
                db.query(ReminderDelivery)
                .filter(
                    ReminderDelivery.status.in_(
                        [
                            ReminderDeliveryStatus.retryable,
                            ReminderDeliveryStatus.attempting,
                        ]
                    )
                )
                .order_by(ReminderDelivery.id.asc())
                .all()
            )
            retry_now = now.astimezone(timezone.utc).replace(tzinfo=None)
            for delivery_row in retry_rows:
                digest = (
                    db.query(ReminderDigest)
                    .filter(ReminderDigest.id == delivery_row.digest_id)
                    .first()
                )
                if not digest:
                    continue
                retry_user = db.query(User).filter(User.id == digest.user_id).first()
                if not retry_user:
                    continue
                retry_preferences = resolve_preferences(db, retry_user.id)
                enabled = (
                    retry_preferences.chat_enabled
                    if delivery_row.channel == "chat"
                    else retry_preferences.email_enabled
                )
                retried = deliver_one_channel(
                    db,
                    digest=digest,
                    user=retry_user,
                    channel_name=delivery_row.channel,
                    enabled=enabled,
                    registry=self.registry,
                    now=retry_now,
                )
                delivered += retried.status == ReminderDeliveryStatus.delivered
                failed += retried.status == ReminderDeliveryStatus.failed

            relative_retry_rows = (
                db.query(TaskReminderDelivery)
                .filter(
                    TaskReminderDelivery.status.in_(
                        [ReminderDeliveryStatus.retryable, ReminderDeliveryStatus.attempting]
                    )
                )
                .order_by(TaskReminderDelivery.id.asc())
                .all()
            )
            retry_now = now.astimezone(timezone.utc).replace(tzinfo=None)
            for delivery_row in relative_retry_rows:
                notification = (
                    db.query(TaskReminderNotification)
                    .filter(TaskReminderNotification.id == delivery_row.notification_id)
                    .first()
                )
                if not notification or not revalidate_task_relative_notification(db, notification):
                    continue
                retry_user = db.query(User).filter(User.id == notification.user_id).first()
                if not retry_user:
                    continue
                retry_preferences = resolve_preferences(db, retry_user.id)
                enabled = (
                    retry_preferences.chat_enabled
                    if delivery_row.channel == "chat"
                    else retry_preferences.email_enabled
                )
                retried = deliver_task_reminder_one_channel(
                    db,
                    notification=notification,
                    user=retry_user,
                    channel_name=delivery_row.channel,
                    enabled=enabled,
                    registry=self.registry,
                    now=retry_now,
                )
                delivered += retried.status == ReminderDeliveryStatus.delivered
                failed += retried.status == ReminderDeliveryStatus.failed

        for user in users:
            preferences = resolve_preferences(db, user.id)
            context = local_run_context(
                now, preferences.timezone, preferences.daily_dispatch_time
            )
            if not preferences.enabled:
                continue

            if deliver:
                relative_notifications = claim_due_task_relative_notifications(
                    db,
                    user_id=user.id,
                    preferences=preferences,
                    now_utc=now,
                    lookback_seconds=max(
                        120, settings.REMINDER_WORKER_INTERVAL_SECONDS + 30
                    ),
                )
                for notification in relative_notifications:
                    if not revalidate_task_relative_notification(db, notification):
                        continue
                    outcomes = deliver_task_reminder_channels(
                        db,
                        notification=notification,
                        user=user,
                        preferences=preferences,
                        registry=self.registry,
                        now=now.astimezone(timezone.utc).replace(tzinfo=None),
                    )
                    delivered += sum(
                        row.status == ReminderDeliveryStatus.delivered
                        for row in outcomes.values()
                    )
                    failed += sum(
                        row.status == ReminderDeliveryStatus.failed
                        for row in outcomes.values()
                    )

            if not context.due:
                continue
            due_users += 1

            if not deliver:
                candidates = list_reminder_candidates(
                    db,
                    user.id,
                    context.local_date,
                    preferences.cadence_offsets,
                )
                candidate_items += len(candidates)
                continue

            claimed = claim_daily_digest(db, user.id, now, preferences)
            if not claimed:
                continue
            digest = claimed.digest
            if digest.state == ReminderDigestState.cancelled:
                continue

            if digest.state == ReminderDigestState.preparing:
                snapshots = finalize_digest_snapshot(db, claimed)
                candidate_items += len(snapshots)
                if not snapshots:
                    continue
                content = await self.agent.generate(
                    db,
                    user_id=user.id,
                    digest_id=digest.id,
                    language=preferences.language,
                    role_card=preferences.role_card,
                    item_snapshots=snapshots,
                    app_base_url=settings.APP_BASE_URL,
                )
                digest.subject = content.subject
                digest.framing_text = content.framing
                digest.body_text = content.body
                digest.chat_url = validated_chat_url(settings.APP_BASE_URL)
                digest.generation_mode = content.mode
                digest.generation_attempts = content.attempts
                digest.state = ReminderDigestState.ready
                db.commit()
                generated += 1

            existing_delivered = (
                db.query(ReminderDelivery)
                .filter(
                    ReminderDelivery.digest_id == digest.id,
                    ReminderDelivery.status == ReminderDeliveryStatus.delivered,
                )
                .count()
            )
            if not existing_delivered:
                previous_count = len(digest.item_snapshot or [])
                snapshots = revalidate_digest_snapshot(db, digest)
                if not snapshots:
                    continue
                if len(snapshots) != previous_count:
                    subject, framing = deterministic_fallback(
                        preferences.language, len(snapshots)
                    )
                    digest.subject = subject
                    digest.framing_text = framing
                    digest.body_text = render_digest_body(
                        framing,
                        preferences.language,
                        snapshots,
                        validated_chat_url(settings.APP_BASE_URL),
                    )
                    digest.generation_mode = ReminderGenerationMode.template
                    db.commit()

            outcomes = deliver_digest_channels(
                db,
                digest=digest,
                user=user,
                preferences=preferences,
                registry=self.registry,
                now=now.astimezone(timezone.utc).replace(tzinfo=None),
            )
            delivered += sum(
                row.status == ReminderDeliveryStatus.delivered
                for row in outcomes.values()
            )
            failed += sum(
                row.status == ReminderDeliveryStatus.failed
                for row in outcomes.values()
            )

        return ReminderRunSummary(
            evaluated_users=len(users),
            due_users=due_users,
            candidate_items=candidate_items,
            generated_digests=generated,
            delivered_channels=delivered,
            failed_channels=failed,
            dry_run=not deliver,
        )
