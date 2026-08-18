"""Parse a ManageBac personal iCalendar feed into bounded task records."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import Calendar

from config import settings
from services.managebac_security import ManageBacIntegrationError


class ManageBacCalendarParseError(ManageBacIntegrationError):
    pass


@dataclass(frozen=True)
class ManageBacCalendarItem:
    uid: str
    kind: str
    title: str
    description: str
    subject: Optional[str]
    deadline: datetime
    source_url: Optional[str]
    sequence: Optional[int]
    last_modified: Optional[datetime]
    status: str
    fingerprint: str

    def snapshot(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "subject": self.subject,
            "deadline": self.deadline.isoformat(),
            "source_url": self.source_url,
            "status": self.status,
        }


@dataclass(frozen=True)
class ManageBacParseResult:
    calendar_name: Optional[str]
    items: tuple[ManageBacCalendarItem, ...]
    total_items: int
    skipped_items: int
    skipped_reasons: tuple[str, ...]


_SPACE_RE = re.compile(r"[ \t\f\v]+")
_TAG_RE = re.compile(r"<[^>]+>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TASK_MARKERS = {
    "task",
    "tasks",
    "assignment",
    "assignments",
    "assessment",
    "assessments",
    "homework",
    "coursework",
}
_DEADLINE_MARKERS = {"deadline", "deadlines", "due date", "due-date"}


def _plain_text(value: object, *, max_length: int) -> str:
    raw = str(value or "")
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</p\s*>", "\n", raw)
    raw = html.unescape(_TAG_RE.sub("", raw))
    raw = _CONTROL_RE.sub("", raw)
    lines = [_SPACE_RE.sub(" ", line).strip() for line in raw.replace("\r", "").split("\n")]
    cleaned = "\n".join(line for line in lines if line).strip()
    return cleaned[:max_length]


def _property_text(component, name: str, *, max_length: int = 2000) -> str:
    value = component.get(name)
    return _plain_text(value, max_length=max_length) if value is not None else ""


def _categories(component) -> list[str]:
    value = component.get("CATEGORIES")
    if value is None:
        return []
    values = getattr(value, "cats", None)
    if values is None:
        values = str(value).split(",")
    cleaned_values = []
    for item in values:
        cleaned = _plain_text(item, max_length=100)
        if cleaned:
            cleaned_values.append(cleaned)
    return cleaned_values


def _source_url(component) -> Optional[str]:
    raw = _property_text(component, "URL", max_length=1000)
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return None
    allowed = any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in settings.MANAGEBAC_ALLOWED_HOST_SUFFIXES
    )
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or not allowed
    ):
        return None
    path_segments = {segment.lower() for segment in parsed.path.split("/") if segment}
    if "token" in path_segments or parsed.path.lower().endswith(".ics"):
        return None
    netloc = host if port is None else f"{host}:{port}"
    # Query strings and fragments are unnecessary for the source badge and
    # may themselves contain credentials.
    return urlunsplit(("https", netloc, parsed.path or "/", "", ""))


def _classification(component, categories: list[str], source_url: Optional[str]) -> Optional[str]:
    if component.name == "VTODO":
        return "task"

    explicit_values = []
    for key in (
        "X-MANAGEBAC-TYPE",
        "X-MANAGEBAC-EVENT-TYPE",
        "X-EVENT-TYPE",
        "X-OBJECT-TYPE",
        "X-TYPE",
    ):
        value = _property_text(component, key, max_length=100)
        if value:
            explicit_values.append(value)

    url_path = ""
    if source_url:
        try:
            url_path = urlsplit(source_url).path
        except ValueError:
            pass
    evidence = " ".join(
        [
            *explicit_values,
            *categories,
            url_path.replace("/", " ").replace("-", " ").replace("_", " "),
            _property_text(component, "SUMMARY", max_length=255),
            _property_text(component, "DESCRIPTION", max_length=500),
        ]
    ).lower()
    tokens = set(re.findall(r"[a-z]+(?:\s+[a-z]+)?", evidence))

    if any(marker in evidence for marker in ("/deadline/", "/deadlines/")):
        return "deadline"
    if any(marker in evidence for marker in ("/task/", "/tasks/", "/assignment/", "/assignments/")):
        return "task"
    if any(marker in tokens or marker in evidence for marker in _DEADLINE_MARKERS):
        return "deadline"
    if any(marker in tokens or marker in evidence for marker in _TASK_MARKERS):
        return "task"
    return None


def _decoded_datetime(component, name: str):
    value = component.get(name)
    if value is None:
        return None
    decoded = getattr(value, "dt", None)
    if decoded is not None:
        return decoded
    try:
        return component.decoded(name)
    except Exception:
        return None


def _as_local_wall_clock(value, timezone_name: str, *, exclusive_end: bool = False) -> Optional[datetime]:
    if value is None:
        return None
    try:
        user_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        user_zone = ZoneInfo("Asia/Shanghai")

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(user_zone).replace(tzinfo=None)
        return value
    if isinstance(value, date):
        local_date = value - timedelta(days=1) if exclusive_end else value
        return datetime.combine(local_date, time(23, 59))
    return None


def _deadline(component, timezone_name: str) -> Optional[datetime]:
    if component.name == "VTODO":
        due = _decoded_datetime(component, "DUE")
        if due is not None:
            return _as_local_wall_clock(due, timezone_name)

    start = _decoded_datetime(component, "DTSTART")
    if start is not None:
        return _as_local_wall_clock(start, timezone_name)

    end = _decoded_datetime(component, "DTEND")
    if end is not None:
        return _as_local_wall_clock(end, timezone_name, exclusive_end=isinstance(end, date) and not isinstance(end, datetime))
    return None


def _last_modified(component) -> Optional[datetime]:
    value = _decoded_datetime(component, "LAST-MODIFIED") or _decoded_datetime(component, "DTSTAMP")
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _sequence(component) -> Optional[int]:
    value = component.get("SEQUENCE")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _subject(component, categories: list[str]) -> Optional[str]:
    explicit = _property_text(component, "X-MANAGEBAC-CLASS", max_length=100)
    if not explicit:
        explicit = _property_text(component, "X-MANAGEBAC-SUBJECT", max_length=100)
    if explicit:
        return explicit
    marker_words = _TASK_MARKERS | _DEADLINE_MARKERS | {"event", "events"}
    for category in categories:
        if category.lower() not in marker_words:
            return category[:100]
    return None


def _fingerprint(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_newer(candidate: ManageBacCalendarItem, current: ManageBacCalendarItem) -> bool:
    candidate_key = (
        candidate.sequence if candidate.sequence is not None else -1,
        candidate.last_modified or datetime.min,
        candidate.fingerprint,
    )
    current_key = (
        current.sequence if current.sequence is not None else -1,
        current.last_modified or datetime.min,
        current.fingerprint,
    )
    return candidate_key > current_key


def parse_managebac_calendar(content: bytes, *, timezone_name: str = "Asia/Shanghai") -> ManageBacParseResult:
    if not content:
        raise ManageBacCalendarParseError("empty_calendar", "ManageBac 日历内容为空")
    try:
        calendar = Calendar.from_ical(content)
    except Exception as exc:
        raise ManageBacCalendarParseError("invalid_calendar", "ManageBac 返回的内容不是有效 iCalendar") from exc

    calendar_name = _property_text(calendar, "X-WR-CALNAME", max_length=255)
    if not calendar_name:
        calendar_name = _property_text(calendar, "NAME", max_length=255)

    by_uid: dict[str, ManageBacCalendarItem] = {}
    total = 0
    skipped_reasons: list[str] = []
    for component in calendar.walk():
        if component.name not in {"VEVENT", "VTODO"}:
            continue
        total += 1
        uid = _property_text(component, "UID", max_length=512)
        if not uid:
            skipped_reasons.append("missing_uid")
            continue
        title = _property_text(component, "SUMMARY", max_length=255)
        if not title:
            skipped_reasons.append("missing_title")
            continue
        deadline = _deadline(component, timezone_name)
        if deadline is None:
            skipped_reasons.append("missing_deadline")
            continue
        categories = _categories(component)
        source_url = _source_url(component)
        kind = _classification(component, categories, source_url)
        if kind is None:
            skipped_reasons.append("unrecognized_event")
            continue
        status_value = _property_text(component, "STATUS", max_length=40).upper()
        state = "cancelled" if status_value == "CANCELLED" else "active"
        description = _property_text(component, "DESCRIPTION", max_length=10000)
        subject = _subject(component, categories)
        snapshot = {
            "kind": kind,
            "title": title,
            "description": description,
            "subject": subject,
            "deadline": deadline.isoformat(),
            "source_url": source_url,
            "status": state,
        }
        item = ManageBacCalendarItem(
            uid=uid,
            kind=kind,
            title=title,
            description=description,
            subject=subject,
            deadline=deadline,
            source_url=source_url,
            sequence=_sequence(component),
            last_modified=_last_modified(component),
            status=state,
            fingerprint=_fingerprint(snapshot),
        )
        current = by_uid.get(uid)
        if current is None or _is_newer(item, current):
            by_uid[uid] = item

    items = tuple(sorted(by_uid.values(), key=lambda item: (item.deadline, item.uid)))
    return ManageBacParseResult(
        calendar_name=calendar_name or None,
        items=items,
        total_items=total,
        skipped_items=max(0, total - len(items)),
        skipped_reasons=tuple(skipped_reasons[:100]),
    )
