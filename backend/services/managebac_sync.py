"""Idempotent personal ManageBac iCalendar synchronization."""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import uuid4

import httpx
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from config import settings
from models.managebac import ManageBacConnection, ManageBacSyncRun, ManageBacTaskLink
from models.reminder import ReminderPreference
from models.task_new import Task, TaskType
from services.managebac_ical import ManageBacParseResult, parse_managebac_calendar
from services.managebac_security import (
    FetchedCalendar,
    ManageBacIntegrationError,
    decrypt_feed_url,
    encrypt_feed_url,
    fetch_calendar,
    normalize_feed_url,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidatedManageBacFeed:
    normalized_url: str
    feed_host: str
    fetched: FetchedCalendar
    parsed: ManageBacParseResult


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user_timezone(db: Session, user_id: int) -> str:
    row = db.query(ReminderPreference.timezone).filter(ReminderPreference.user_id == user_id).first()
    return row[0] if row and row[0] else "Asia/Shanghai"


async def validate_managebac_feed(
    db: Session,
    user_id: int,
    feed_url: str,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    resolve_addresses: Optional[Callable[[str], list[str]]] = None,
) -> ValidatedManageBacFeed:
    normalized = normalize_feed_url(feed_url)
    fetched = await fetch_calendar(
        normalized.url,
        transport=transport,
        resolve_addresses=resolve_addresses,
    )
    if fetched.http_status == 304:
        raise ManageBacIntegrationError("unexpected_not_modified", "无法验证未返回内容的日历")
    parsed = parse_managebac_calendar(
        fetched.content,
        timezone_name=_user_timezone(db, user_id),
    )
    return ValidatedManageBacFeed(
        normalized_url=normalized.url,
        feed_host=normalized.host,
        fetched=fetched,
        parsed=parsed,
    )


def connection_status_payload(connection: Optional[ManageBacConnection]) -> dict:
    if connection is None:
        return {
            "connected": False,
            "enabled": False,
            "sync_interval_minutes": settings.MANAGEBAC_SYNC_INTERVAL_MINUTES,
        }
    return {
        "connected": True,
        "status": connection.status,
        "enabled": bool(connection.enabled),
        "feed_host": connection.feed_host,
        "sync_interval_minutes": connection.sync_interval_minutes,
        "next_sync_at": connection.next_sync_at,
        "last_success_at": connection.last_success_at,
        "consecutive_failures": connection.consecutive_failures,
        "last_error_code": connection.last_error_code,
        "last_error_detail": connection.last_error_detail,
    }


def validation_payload(validated: ValidatedManageBacFeed) -> dict:
    return {
        "valid": True,
        "feed_host": validated.feed_host,
        "calendar_name": validated.parsed.calendar_name,
        "total_items": validated.parsed.total_items,
        "importable_items": len(validated.parsed.items),
        "skipped_items": validated.parsed.skipped_items,
        "preview": [
            {
                "title": item.title,
                "subject": item.subject,
                "deadline": item.deadline,
                "kind": item.kind,
            }
            for item in validated.parsed.items[:5]
        ],
    }


def _snapshot_deadline(snapshot: Optional[dict]) -> Optional[datetime]:
    value = (snapshot or {}).get("deadline")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _same_wall_clock(left: Optional[datetime], right: Optional[datetime]) -> bool:
    if left is None or right is None:
        return left is right
    left_value = left.replace(tzinfo=None) if left.tzinfo else left
    right_value = right.replace(tzinfo=None) if right.tzinfo else right
    return left_value == right_value


def _remote_revision_is_stale(item, link: ManageBacTaskLink) -> bool:
    if item.sequence is not None and link.remote_sequence is not None:
        if item.sequence != link.remote_sequence:
            return item.sequence < link.remote_sequence
    if item.last_modified is not None and link.remote_last_modified is not None:
        return item.last_modified < link.remote_last_modified
    return False


def _new_task(user_id: int, item) -> Task:
    return Task(
        user_id=user_id,
        id_name="",
        task_type=TaskType.todo,
        title=item.title,
        description=item.description or None,
        subject=item.subject,
        priority="medium",
        status="todo",
        deadline=item.deadline,
        hard_deadline_date=item.deadline.date(),
        reminder_offsets_minutes=None,
        estimated_hours=0,
        progress=0,
        effort_source="managebac",
        is_schedule_locked=False,
    )


def _apply_calendar_items(
    db: Session,
    connection: ManageBacConnection,
    parsed: ManageBacParseResult,
    run: ManageBacSyncRun,
) -> bool:
    now = utc_now_naive()
    links = db.query(ManageBacTaskLink).filter(
        ManageBacTaskLink.connection_id == connection.id
    ).all()
    by_uid = {link.external_uid: link for link in links}
    seen: set[str] = set()
    mutated = False

    run.total_items = parsed.total_items
    run.skipped_count = parsed.skipped_items
    for item in parsed.items:
        seen.add(item.uid)
        link = by_uid.get(item.uid)
        if link is None:
            if item.status == "cancelled":
                run.cancelled_count += 1
                continue
            task = _new_task(connection.user_id, item)
            db.add(task)
            db.flush()
            link = ManageBacTaskLink(
                connection_id=connection.id,
                external_uid=item.uid,
                task_id=task.id,
                remote_hash=item.fingerprint,
                remote_sequence=item.sequence,
                remote_last_modified=item.last_modified,
                remote_snapshot=item.snapshot(),
                source_url=item.source_url,
                remote_state="active",
                first_seen_at=now,
                last_seen_at=now,
                missing_count=0,
            )
            db.add(link)
            by_uid[item.uid] = link
            run.added_count += 1
            mutated = True
            continue

        task = db.query(Task).filter(
            Task.id == link.task_id,
            Task.user_id == connection.user_id,
        ).first()
        if task is None:
            # The FK normally removes the link when a user deletes the local
            # task.  This fallback heals legacy databases without cascades.
            db.delete(link)
            db.flush()
            if item.status == "cancelled":
                run.cancelled_count += 1
                continue
            task = _new_task(connection.user_id, item)
            db.add(task)
            db.flush()
            link = ManageBacTaskLink(
                connection_id=connection.id,
                external_uid=item.uid,
                task_id=task.id,
                remote_hash=item.fingerprint,
                remote_sequence=item.sequence,
                remote_last_modified=item.last_modified,
                remote_snapshot=item.snapshot(),
                source_url=item.source_url,
                remote_state=item.status,
                first_seen_at=now,
                last_seen_at=now,
                missing_count=0,
            )
            db.add(link)
            run.added_count += 1
            mutated = True
            continue

        previous_deadline = _snapshot_deadline(link.remote_snapshot)
        if _remote_revision_is_stale(item, link):
            link.last_seen_at = now
            link.missing_count = 0
            run.unchanged_count += 1
            continue
        if item.status == "cancelled":
            if link.remote_state != "cancelled" or link.remote_hash != item.fingerprint:
                if _same_wall_clock(task.deadline, previous_deadline):
                    task.deadline = None
                    if previous_deadline and task.hard_deadline_date == previous_deadline.date():
                        task.hard_deadline_date = None
                link.remote_state = "cancelled"
                link.remote_hash = item.fingerprint
                link.remote_sequence = item.sequence
                link.remote_last_modified = item.last_modified
                link.remote_snapshot = item.snapshot()
                link.source_url = item.source_url
                run.cancelled_count += 1
                mutated = True
            else:
                run.unchanged_count += 1
        elif link.remote_hash != item.fingerprint or link.remote_state != "active":
            task.title = item.title
            task.description = item.description or None
            task.subject = item.subject
            task.deadline = item.deadline
            task.hard_deadline_date = item.deadline.date()
            task.effort_source = "managebac"
            link.remote_state = "active"
            link.remote_hash = item.fingerprint
            link.remote_sequence = item.sequence
            link.remote_last_modified = item.last_modified
            link.remote_snapshot = item.snapshot()
            link.source_url = item.source_url
            run.updated_count += 1
            mutated = True
        else:
            run.unchanged_count += 1

        link.last_seen_at = now
        link.missing_count = 0

    for link in links:
        if link.external_uid not in seen:
            link.missing_count = int(link.missing_count or 0) + 1
    return mutated


def _run_payload(run: ManageBacSyncRun) -> dict:
    return {
        "status": run.status,
        "http_status": run.http_status,
        "total_items": run.total_items,
        "added_count": run.added_count,
        "updated_count": run.updated_count,
        "unchanged_count": run.unchanged_count,
        "cancelled_count": run.cancelled_count,
        "skipped_count": run.skipped_count,
        "error_code": run.error_code,
    }


def _successful_run(
    db: Session,
    connection: ManageBacConnection,
    run: ManageBacSyncRun,
    *,
    fetched: FetchedCalendar,
    parsed: Optional[ManageBacParseResult],
) -> dict:
    mutated = False
    if parsed is not None:
        mutated = _apply_calendar_items(db, connection, parsed, run)
    connection.etag = fetched.etag or connection.etag
    connection.last_modified = fetched.last_modified or connection.last_modified
    connection.status = "active" if connection.enabled else "paused"
    connection.last_success_at = utc_now_naive()
    connection.consecutive_failures = 0
    connection.last_error_code = None
    connection.last_error_detail = None
    connection.next_sync_at = utc_now_naive() + timedelta(minutes=connection.sync_interval_minutes)
    run.http_status = fetched.http_status
    run.status = "success"
    run.finished_at = utc_now_naive()
    db.commit()

    if mutated:
        try:
            from services.schedule_triggers import analyze_after_mutation

            analyze_after_mutation(db, connection.user_id, "managebac_sync")
        except Exception:
            db.rollback()
            logger.exception("ManageBac sync completed but schedule analysis failed for user_id=%s", connection.user_id)
    return _run_payload(run)


def _failed_run(
    db: Session,
    connection: ManageBacConnection,
    run: ManageBacSyncRun,
    error: ManageBacIntegrationError,
) -> dict:
    failures = int(connection.consecutive_failures or 0) + 1
    connection.consecutive_failures = failures
    connection.last_error_code = error.code
    connection.last_error_detail = error.safe_detail
    # A 403 can be emitted by ManageBac's edge policy for a calendar client
    # even when the bearer URL is valid (for example, Google Calendar can read
    # the same feed). Treat it as retryable rather than telling the user to
    # rotate a valid credential. 401/404/410 still indicate a missing or
    # withdrawn subscription after repeated attempts.
    permanent_status = error.http_status in {401, 404, 410}
    unrecoverable_credential = error.code == "credential_decrypt_failed"
    if unrecoverable_credential or (permanent_status and failures >= 3):
        connection.status = "reconnect_required"
        connection.enabled = False
        connection.next_sync_at = None
    else:
        connection.status = "error" if connection.enabled else "paused"
        delay_minutes = min(60, connection.sync_interval_minutes * (2 ** min(failures - 1, 3)))
        delay_seconds = error.retry_after_seconds or delay_minutes * 60
        connection.next_sync_at = utc_now_naive() + timedelta(seconds=delay_seconds)

    run.status = "failed"
    run.http_status = error.http_status
    run.error_code = error.code
    run.error_detail = error.safe_detail
    run.finished_at = utc_now_naive()
    db.commit()
    return _run_payload(run)


async def connect_managebac_feed(
    db: Session,
    user_id: int,
    feed_url: str,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    resolve_addresses: Optional[Callable[[str], list[str]]] = None,
) -> tuple[ManageBacConnection, ValidatedManageBacFeed, dict]:
    validated = await validate_managebac_feed(
        db,
        user_id,
        feed_url,
        transport=transport,
        resolve_addresses=resolve_addresses,
    )
    now = utc_now_naive()
    connection = db.query(ManageBacConnection).filter(
        ManageBacConnection.user_id == user_id
    ).first()
    if connection is None:
        connection = ManageBacConnection(user_id=user_id)
        db.add(connection)
    elif connection.feed_host and connection.feed_host != validated.feed_host:
        # A different school is a new source.  Preserve imported local tasks,
        # but drop mappings so the new feed cannot mutate the old school's data.
        db.query(ManageBacTaskLink).filter(
            ManageBacTaskLink.connection_id == connection.id
        ).delete(synchronize_session=False)

    connection.encrypted_feed_url = encrypt_feed_url(validated.normalized_url)
    connection.feed_host = validated.feed_host
    connection.status = "active"
    connection.enabled = True
    connection.sync_interval_minutes = settings.MANAGEBAC_SYNC_INTERVAL_MINUTES
    connection.etag = validated.fetched.etag
    connection.last_modified = validated.fetched.last_modified
    connection.next_sync_at = now
    connection.consecutive_failures = 0
    connection.last_error_code = None
    connection.last_error_detail = None
    db.flush()
    run = ManageBacSyncRun(connection_id=connection.id, trigger="initial", status="running", started_at=now)
    db.add(run)
    db.flush()
    summary = _successful_run(
        db,
        connection,
        run,
        fetched=validated.fetched,
        parsed=validated.parsed,
    )
    db.refresh(connection)
    return connection, validated, summary


async def sync_managebac_connection(
    db: Session,
    connection: ManageBacConnection,
    *,
    trigger: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    resolve_addresses: Optional[Callable[[str], list[str]]] = None,
) -> dict:
    now = utc_now_naive()
    connection.last_sync_started_at = now
    run = ManageBacSyncRun(connection_id=connection.id, trigger=trigger, status="running", started_at=now)
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        feed_url = decrypt_feed_url(connection.encrypted_feed_url)
        fetched = await fetch_calendar(
            feed_url,
            etag=connection.etag,
            last_modified=connection.last_modified,
            transport=transport,
            resolve_addresses=resolve_addresses,
        )
        parsed = None
        if fetched.http_status != 304:
            parsed = parse_managebac_calendar(
                fetched.content,
                timezone_name=_user_timezone(db, connection.user_id),
            )
        return _successful_run(db, connection, run, fetched=fetched, parsed=parsed)
    except ManageBacIntegrationError as error:
        db.rollback()
        connection = db.query(ManageBacConnection).filter(ManageBacConnection.id == connection.id).one()
        run = db.query(ManageBacSyncRun).filter(ManageBacSyncRun.id == run.id).one()
        return _failed_run(db, connection, run, error)
    except Exception:
        db.rollback()
        logger.exception("Unexpected ManageBac synchronization failure for connection_id=%s", connection.id)
        connection = db.query(ManageBacConnection).filter(ManageBacConnection.id == connection.id).one()
        run = db.query(ManageBacSyncRun).filter(ManageBacSyncRun.id == run.id).one()
        error = ManageBacIntegrationError("unexpected_error", "同步过程中发生意外错误")
        return _failed_run(db, connection, run, error)


async def sync_due_managebac_connections(session_factory) -> dict:
    """Claim and synchronize due connections; safe across multiple workers."""

    now = utc_now_naive()
    owner = f"{socket.gethostname()}-{uuid4().hex[:12]}"
    with session_factory() as db:
        history_cutoff = now - timedelta(days=90)
        db.query(ManageBacSyncRun).filter(
            or_(
                ManageBacSyncRun.finished_at < history_cutoff,
                and_(
                    ManageBacSyncRun.finished_at.is_(None),
                    ManageBacSyncRun.started_at < history_cutoff,
                ),
            )
        ).delete(synchronize_session=False)
        db.commit()
        candidate_ids = [
            row[0]
            for row in db.query(ManageBacConnection.id).filter(
                ManageBacConnection.enabled.is_(True),
                ManageBacConnection.next_sync_at.isnot(None),
                ManageBacConnection.next_sync_at <= now,
                or_(
                    ManageBacConnection.lease_expires_at.is_(None),
                    ManageBacConnection.lease_expires_at < now,
                ),
            ).order_by(ManageBacConnection.next_sync_at.asc()).limit(50).all()
        ]

    succeeded = 0
    failed = 0
    for connection_id in candidate_ids:
        with session_factory() as db:
            claimed = db.query(ManageBacConnection).filter(
                ManageBacConnection.id == connection_id,
                ManageBacConnection.enabled.is_(True),
                or_(
                    ManageBacConnection.lease_expires_at.is_(None),
                    ManageBacConnection.lease_expires_at < utc_now_naive(),
                ),
            ).update(
                {
                    ManageBacConnection.lease_owner: owner,
                    ManageBacConnection.lease_expires_at: utc_now_naive() + timedelta(minutes=5),
                },
                synchronize_session=False,
            )
            db.commit()
            if not claimed:
                continue
            try:
                connection = db.query(ManageBacConnection).filter(
                    ManageBacConnection.id == connection_id
                ).one()
                summary = await sync_managebac_connection(db, connection, trigger="automatic")
                if summary["status"] == "success":
                    succeeded += 1
                else:
                    failed += 1
            except Exception:
                db.rollback()
                failed += 1
                logger.exception(
                    "ManageBac connection sync escaped isolation for connection_id=%s",
                    connection_id,
                )
            finally:
                try:
                    current = db.query(ManageBacConnection).filter(
                        ManageBacConnection.id == connection_id
                    ).first()
                    if current and current.lease_owner == owner:
                        current.lease_owner = None
                        current.lease_expires_at = None
                        db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "ManageBac lease release failed for connection_id=%s",
                        connection_id,
                    )
    return {"evaluated": len(candidate_ids), "succeeded": succeeded, "failed": failed}


def disconnect_managebac(
    db: Session,
    user_id: int,
    *,
    delete_imported_tasks: bool,
) -> int:
    connection = db.query(ManageBacConnection).filter(
        ManageBacConnection.user_id == user_id
    ).first()
    if connection is None:
        return 0
    task_ids = [
        row[0]
        for row in db.query(ManageBacTaskLink.task_id).filter(
            ManageBacTaskLink.connection_id == connection.id
        ).all()
    ]
    # Delete children explicitly so disconnect behaves consistently even when
    # a local/test database has not enabled foreign-key cascade enforcement.
    db.query(ManageBacTaskLink).filter(
        ManageBacTaskLink.connection_id == connection.id
    ).delete(synchronize_session=False)
    db.query(ManageBacSyncRun).filter(
        ManageBacSyncRun.connection_id == connection.id
    ).delete(synchronize_session=False)
    deleted = 0
    if delete_imported_tasks and task_ids:
        deleted = db.query(Task).filter(
            Task.user_id == user_id,
            Task.id.in_(task_ids),
        ).delete(synchronize_session=False)
    db.delete(connection)
    db.commit()
    return int(deleted or 0)
