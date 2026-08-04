"""Run a bounded automatic-worker acceptance gate for timed reminders.

This script uses the same ``reminder_worker.run_once`` function as the
standalone daemon and never calls the admin reminder endpoint.  It creates a
temporary test user that uses the selected recipient's email, so existing
tasks and daily digests are not changed.  The temporary user is removed at
the end.  Output is intentionally sanitized.
"""

import argparse
import asyncio
import time as time_module
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import models  # noqa: F401 - register metadata
from sqlalchemy import text
from database import SessionLocal
from models.reminder import (
    ReminderDelivery,
    ReminderDigest,
    ReminderGenerationMode,
    TaskReminderDelivery,
    TaskReminderNotification,
)
from models.task_new import Task, TaskType
from models.user import User
from reminder_worker import run_once
from services.reminder_agent import GeneratedReminderContent
from services.reminder_orchestrator import ReminderOrchestrator
from services.reminder_preferences import resolve_preferences, update_preferences


def _local_now(timezone_name: str) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)


class AcceptanceTextAgent:
    """Keep this gate focused on scheduling and real channel delivery.

    The production Worker still uses ReminderTextAgent.  The provider-specific
    LLM gate is separate because a slow/unavailable provider must not make a
    five-minute SMTP scheduling gate hang indefinitely.
    """

    async def generate(self, db, **kwargs):
        titles = [item.get("title", "") for item in kwargs["item_snapshots"]]
        return GeneratedReminderContent(
            subject="Timed reminder acceptance",
            framing="Controlled automatic reminder acceptance.",
            body="Controlled automatic reminder acceptance.\n\n"
            + "\n".join(f"- {title}" for title in titles),
            mode=ReminderGenerationMode.template,
            attempts=0,
        )


_acceptance_orchestrator = None


async def _tick() -> None:
    global _acceptance_orchestrator
    if _acceptance_orchestrator is None:
        _acceptance_orchestrator = ReminderOrchestrator(agent=AcceptanceTextAgent())
    await run_once(orchestrator=_acceptance_orchestrator)


def _tick_and_sleep(seconds: int) -> None:
    asyncio.run(_tick())
    time_module.sleep(seconds)


def run_gate(user_id: int, timeout_seconds: int, poll_seconds: int) -> dict:
    suffix = uuid4().hex[:10]
    task_ids: list[int] = []
    target_user_id = None
    target_timezone = None
    dispatch_date = None
    try:
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).one()
            preferences = resolve_preferences(db, user_id)
            if not user.email:
                return {"status": "FAIL", "stage": "recipient_has_no_email"}
            test_user = User(
                username=f"timed_acceptance_{suffix}",
                email=user.email,
                password="temporary-acceptance-user",
            )
            db.add(test_user)
            db.flush()
            target_user_id = test_user.id
            # Existing reminder tables in deployed databases may still have
            # their legacy FK pointed at ``users``.  Bridge this synthetic
            # account by the same id for the duration of the gate.
            db.execute(
                text(
                    "INSERT INTO users "
                    "(id, username, email, password_hash, is_admin) "
                    "VALUES (:id, :username, :email, :password_hash, 0)"
                ),
                {
                    "id": target_user_id,
                    "username": f"timed_acceptance_{suffix}",
                    "email": f"timed_acceptance_{suffix}@example.invalid",
                    "password_hash": "acceptance-only",
                },
            )
            target_timezone = preferences.timezone
            now_local = _local_now(preferences.timezone)
            dispatch_at = now_local + timedelta(minutes=5)
            dispatch_date = now_local.date()
            dispatch_time = dispatch_at.strftime("%H:%M")
            daily_today = Task(
                user_id=target_user_id,
                task_type=TaskType.todo,
                title=f"timed-acceptance-d0-{suffix}",
                status="todo",
                deadline=now_local.replace(hour=23, minute=59, second=0, microsecond=0),
            )
            daily_tomorrow = Task(
                user_id=target_user_id,
                task_type=TaskType.todo,
                title=f"timed-acceptance-d-1-{suffix}",
                status="todo",
                deadline=(now_local + timedelta(days=1)).replace(
                    hour=23, minute=59, second=0, microsecond=0
                ),
            )
            db.add_all([daily_today, daily_tomorrow])
            db.flush()
            task_ids.extend([daily_today.id, daily_tomorrow.id])
            update_preferences(
                db,
                target_user_id,
                enabled=True,
                daily_dispatch_time=dispatch_time,
                email_enabled=True,
                chat_enabled=True,
            )

        deadline = time_module.monotonic() + timeout_seconds
        digest = None
        while time_module.monotonic() < deadline:
            _tick_and_sleep(poll_seconds)
            with SessionLocal() as db:
                digest = (
                    db.query(ReminderDigest)
                    .filter(
                        ReminderDigest.user_id == target_user_id,
                        ReminderDigest.local_date == dispatch_date,
                    )
                    .first()
                )
                if digest and digest.item_snapshot:
                    break
        if not digest or not digest.item_snapshot:
            return {"status": "FAIL", "stage": "daily_digest_timeout"}

        daily_titles = {item.get("title") for item in digest.item_snapshot}
        expected_daily_titles = {
            f"timed-acceptance-d0-{suffix}", f"timed-acceptance-d-1-{suffix}"
        }

        with SessionLocal() as db:
            now_local = _local_now(target_timezone)
            relative_five = Task(
                user_id=target_user_id,
                task_type=TaskType.todo,
                title=f"timed-acceptance-relative-5m-{suffix}",
                status="todo",
                deadline=now_local + timedelta(minutes=6),
            )
            relative_day = Task(
                user_id=target_user_id,
                task_type=TaskType.todo,
                title=f"timed-acceptance-relative-1d-{suffix}",
                status="todo",
                deadline=now_local + timedelta(days=1, minutes=6),
            )
            db.add_all([relative_five, relative_day])
            db.flush()
            task_ids.extend([relative_five.id, relative_day.id])
            db.commit()

        deadline = time_module.monotonic() + timeout_seconds
        while time_module.monotonic() < deadline:
            _tick_and_sleep(poll_seconds)
            with SessionLocal() as db:
                relative_count = db.query(TaskReminderNotification).filter(
                    TaskReminderNotification.user_id == target_user_id,
                    TaskReminderNotification.task_id.in_(task_ids[-2:]),
                ).count()
                if relative_count == 2:
                    break

        with SessionLocal() as db:
            notifications = db.query(TaskReminderNotification).filter(
                TaskReminderNotification.user_id == target_user_id,
                TaskReminderNotification.task_id.in_(task_ids[-2:]),
            ).all()
            deliveries = db.query(TaskReminderDelivery).filter(
                TaskReminderDelivery.notification_id.in_([row.id for row in notifications])
            ).all()
            daily_deliveries = db.query(ReminderDelivery).filter(
                ReminderDelivery.digest_id == digest.id
            ).all()
            daily_channel_statuses = {
                row.channel: row.status.value for row in daily_deliveries
            }
            daily_channels_passed = daily_channel_statuses.get("chat") == "delivered" and daily_channel_statuses.get("email") == "delivered"
            return {
                "status": "PASS" if (
                    daily_titles == expected_daily_titles
                    and daily_channels_passed
                    and {row.offset_minutes for row in notifications} == {5, 1440}
                    and len(deliveries) == 4
                    and all(row.status.value in {"delivered", "skipped", "failed"} for row in deliveries)
                ) else "FAIL",
                "daily_digest_id": digest.id,
                "daily_item_count": len(digest.item_snapshot),
                "daily_titles_match": daily_titles == expected_daily_titles,
                "daily_delivery_statuses": daily_channel_statuses,
                "relative_notification_count": len(notifications),
                "relative_offsets": sorted(row.offset_minutes for row in notifications),
                "relative_delivery_statuses": sorted(row.status.value for row in deliveries),
                "email_delivery_statuses": sorted(
                    row.status.value for row in deliveries if row.channel == "email"
                ),
                "chat_delivery_statuses": sorted(
                    row.status.value for row in deliveries if row.channel == "chat"
                ),
            }
    finally:
        with SessionLocal() as db:
            if target_user_id:
                test_user = db.query(User).filter(User.id == target_user_id).first()
                if test_user:
                    db.delete(test_user)
                db.execute(text("DELETE FROM users WHERE id = :id"), {"id": target_user_id})
            db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run automatic timed-reminder acceptance")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args()
    result = run_gate(args.user_id, max(30, args.timeout_seconds), max(10, args.poll_seconds))
    print(result)
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
