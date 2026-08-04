import re
from dataclasses import dataclass
from typing import Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.reminder import ReminderPreference, ReminderRoleCard


DEFAULT_LANGUAGE = "zh-CN"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_CADENCE_OFFSETS = (2, 1, 0, -1, -3, -7)
DEFAULT_DAILY_DISPATCH_TIME = "09:00"
DEFAULT_TASK_REMINDER_OFFSETS_MINUTES = (5, 1440)
MAX_TASK_REMINDER_OFFSET_MINUTES = 7 * 24 * 60
DEFAULT_ROLE_CARD_SLUG = "friendly-warm-guy"
# The baseline cadence remains mandatory.  Users may add overdue D+N points
# without weakening the pre-deadline coverage that the product guarantees.
BASE_CADENCE_OFFSETS = frozenset(DEFAULT_CADENCE_OFFSETS)
MIN_CUSTOM_OVERDUE_DAYS = 2
MAX_CUSTOM_OVERDUE_DAYS = 365
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
DISPATCH_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class ResolvedReminderPreferences:
    user_id: int
    enabled: bool
    language: str
    timezone: str
    cadence_offsets: tuple[int, ...]
    daily_dispatch_time: str
    default_task_reminder_offsets_minutes: tuple[int, ...]
    email_enabled: bool
    chat_enabled: bool
    role_card: Optional[ReminderRoleCard]
    persisted_id: Optional[int] = None


@dataclass(frozen=True)
class ResolvedRoleCardSelection:
    role_card: Optional[ReminderRoleCard]
    status: str


def normalize_language(value: str) -> str:
    raw = (value or "").strip()
    if not LANGUAGE_RE.fullmatch(raw):
        raise ValueError("语言必须是有效的 BCP 47 标识")
    parts = raw.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        normalized.append(part.upper() if len(part) == 2 else part)
    return "-".join(normalized)


def validate_timezone(value: str) -> str:
    name = (value or "").strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("时区必须是有效的 IANA timezone") from exc
    return name


def normalize_daily_dispatch_time(value: str) -> str:
    normalized = (value or "").strip()
    if not DISPATCH_TIME_RE.fullmatch(normalized):
        raise ValueError("每日提醒时间必须是 HH:MM（00:00 至 23:59）")
    return normalized


def normalize_task_reminder_offsets_minutes(values: Iterable[int]) -> tuple[int, ...]:
    try:
        raw_values = tuple(values)
        if any(isinstance(value, bool) for value in raw_values):
            raise ValueError
        normalized = tuple(dict.fromkeys(int(value) for value in raw_values))
    except (TypeError, ValueError) as exc:
        raise ValueError("任务提醒分钟档位格式无效") from exc
    if len(normalized) > 10 or any(
        value < 1 or value > MAX_TASK_REMINDER_OFFSET_MINUTES for value in normalized
    ):
        raise ValueError("任务提醒分钟档位必须是 1 至 10080 分钟，且最多 10 个")
    return tuple(sorted(normalized))


def normalize_cadence_offsets(values: Iterable[int]) -> tuple[int, ...]:
    try:
        raw_values = tuple(values)
        if any(isinstance(value, bool) for value in raw_values):
            raise ValueError
        normalized = tuple(dict.fromkeys(int(value) for value in raw_values))
    except (TypeError, ValueError) as exc:
        raise ValueError("提醒档位格式无效") from exc
    if not BASE_CADENCE_OFFSETS.issubset(normalized):
        raise ValueError("提醒档位必须保留 D-2、D-1、D0、D+1、D+3、D+7 基础节点")

    custom_offsets = set(normalized) - BASE_CADENCE_OFFSETS
    invalid = [
        offset
        for offset in custom_offsets
        if not (-MAX_CUSTOM_OVERDUE_DAYS <= offset <= -MIN_CUSTOM_OVERDUE_DAYS)
    ]
    if invalid:
        raise ValueError(
            f"自定义提醒仅支持 D+{MIN_CUSTOM_OVERDUE_DAYS} 至 "
            f"D+{MAX_CUSTOM_OVERDUE_DAYS} 的整数天数"
        )

    # Stable, chronological order makes the API response predictable for the
    # future settings UI: pre-deadline -> D0 -> overdue days.
    before_due = tuple(offset for offset in DEFAULT_CADENCE_OFFSETS if offset >= 0)
    overdue = tuple(sorted((offset for offset in normalized if offset < 0), reverse=True))
    return before_due + overdue


def get_default_role_card(db: Session) -> Optional[ReminderRoleCard]:
    card = (
        db.query(ReminderRoleCard)
        .filter(
            ReminderRoleCard.slug == DEFAULT_ROLE_CARD_SLUG,
            ReminderRoleCard.is_active.is_(True),
            ReminderRoleCard.scope == "global",
            ReminderRoleCard.owner_user_id.is_(None),
        )
        .first()
    )
    if card:
        return card
    return (
        db.query(ReminderRoleCard)
        .filter(
            ReminderRoleCard.is_active.is_(True),
            ReminderRoleCard.scope == "global",
            ReminderRoleCard.owner_user_id.is_(None),
        )
        .order_by(ReminderRoleCard.id.asc())
        .first()
    )


def get_selectable_role_card(db: Session, card_id: int) -> ReminderRoleCard:
    card = (
        db.query(ReminderRoleCard)
        .filter(
            ReminderRoleCard.id == card_id,
            ReminderRoleCard.is_active.is_(True),
            ReminderRoleCard.scope == "global",
            ReminderRoleCard.owner_user_id.is_(None),
        )
        .first()
    )
    if not card:
        raise ValueError("角色卡不存在、未启用或不可访问")
    return card


def resolve_role_card_selection(
    db: Session, user_id: int
) -> ResolvedRoleCardSelection:
    """Resolve the shared role card used by reminders and the main agent.

    This is intentionally read-only. Missing preferences do not materialize a
    row merely because a user opened chat.
    """
    row = (
        db.query(ReminderPreference)
        .filter(ReminderPreference.user_id == user_id)
        .first()
    )
    if row and row.role_card_id:
        selected = (
            db.query(ReminderRoleCard)
            .filter(
                ReminderRoleCard.id == row.role_card_id,
                ReminderRoleCard.is_active.is_(True),
                ReminderRoleCard.scope == "global",
                ReminderRoleCard.owner_user_id.is_(None),
            )
            .first()
        )
        if selected:
            return ResolvedRoleCardSelection(role_card=selected, status="selected")

    default_card = get_default_role_card(db)
    if default_card:
        return ResolvedRoleCardSelection(role_card=default_card, status="default")
    return ResolvedRoleCardSelection(role_card=None, status="neutral")


def resolve_preferences(db: Session, user_id: int) -> ResolvedReminderPreferences:
    row = (
        db.query(ReminderPreference)
        .filter(ReminderPreference.user_id == user_id)
        .first()
    )
    role_selection = resolve_role_card_selection(db, user_id)
    if not row:
        return ResolvedReminderPreferences(
            user_id=user_id,
            enabled=True,
            language=DEFAULT_LANGUAGE,
            timezone=DEFAULT_TIMEZONE,
            cadence_offsets=DEFAULT_CADENCE_OFFSETS,
            daily_dispatch_time=DEFAULT_DAILY_DISPATCH_TIME,
            default_task_reminder_offsets_minutes=DEFAULT_TASK_REMINDER_OFFSETS_MINUTES,
            email_enabled=True,
            chat_enabled=True,
            role_card=role_selection.role_card,
        )

    return ResolvedReminderPreferences(
        user_id=user_id,
        enabled=bool(row.enabled),
        language=normalize_language(row.language),
        timezone=validate_timezone(row.timezone),
        cadence_offsets=normalize_cadence_offsets(row.cadence_offsets),
        daily_dispatch_time=normalize_daily_dispatch_time(
            getattr(row, "daily_dispatch_time", None) or DEFAULT_DAILY_DISPATCH_TIME
        ),
        default_task_reminder_offsets_minutes=normalize_task_reminder_offsets_minutes(
            getattr(row, "default_task_reminder_offsets_minutes", None)
            or DEFAULT_TASK_REMINDER_OFFSETS_MINUTES
        ),
        email_enabled=bool(row.email_enabled),
        chat_enabled=bool(row.chat_enabled),
        role_card=role_selection.role_card,
        persisted_id=row.id,
    )


def ensure_preferences(db: Session, user_id: int) -> ReminderPreference:
    existing = (
        db.query(ReminderPreference)
        .filter(ReminderPreference.user_id == user_id)
        .first()
    )
    if existing:
        return existing

    default_card = get_default_role_card(db)
    row = ReminderPreference(
        user_id=user_id,
        enabled=True,
        language=DEFAULT_LANGUAGE,
        timezone=DEFAULT_TIMEZONE,
        cadence_offsets=list(DEFAULT_CADENCE_OFFSETS),
        daily_dispatch_time=DEFAULT_DAILY_DISPATCH_TIME,
        default_task_reminder_offsets_minutes=list(DEFAULT_TASK_REMINDER_OFFSETS_MINUTES),
        email_enabled=True,
        chat_enabled=True,
        role_card_id=default_card.id if default_card else None,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        # Start a fresh snapshot before reading a row committed by a competing
        # first-access request under MySQL REPEATABLE READ.
        db.rollback()
        existing = (
            db.query(ReminderPreference)
            .filter(ReminderPreference.user_id == user_id)
            .first()
        )
        if existing:
            return existing
        raise


def update_preferences(
    db: Session,
    user_id: int,
    *,
    enabled: Optional[bool] = None,
    language: Optional[str] = None,
    timezone: Optional[str] = None,
    cadence_offsets: Optional[Iterable[int]] = None,
    daily_dispatch_time: Optional[str] = None,
    default_task_reminder_offsets_minutes: Optional[Iterable[int]] = None,
    email_enabled: Optional[bool] = None,
    chat_enabled: Optional[bool] = None,
    role_card_id: Optional[int] = None,
    role_card_supplied: bool = False,
) -> ReminderPreference:
    row = ensure_preferences(db, user_id)
    if enabled is not None:
        row.enabled = enabled
    if language is not None:
        row.language = normalize_language(language)
    if timezone is not None:
        row.timezone = validate_timezone(timezone)
    if cadence_offsets is not None:
        row.cadence_offsets = list(normalize_cadence_offsets(cadence_offsets))
    if daily_dispatch_time is not None:
        row.daily_dispatch_time = normalize_daily_dispatch_time(daily_dispatch_time)
    if default_task_reminder_offsets_minutes is not None:
        row.default_task_reminder_offsets_minutes = list(
            normalize_task_reminder_offsets_minutes(default_task_reminder_offsets_minutes)
        )
    if email_enabled is not None:
        row.email_enabled = email_enabled
    if chat_enabled is not None:
        row.chat_enabled = chat_enabled
    if role_card_supplied:
        card = get_default_role_card(db) if role_card_id is None else get_selectable_role_card(db, role_card_id)
        row.role_card_id = card.id if card else None
    row.version = int(row.version or 0) + 1
    db.commit()
    db.refresh(row)
    return row


def list_active_global_cards(db: Session) -> list[ReminderRoleCard]:
    return (
        db.query(ReminderRoleCard)
        .filter(
            ReminderRoleCard.is_active.is_(True),
            ReminderRoleCard.scope == "global",
            ReminderRoleCard.owner_user_id.is_(None),
        )
        .order_by(ReminderRoleCard.id.asc())
        .all()
    )
