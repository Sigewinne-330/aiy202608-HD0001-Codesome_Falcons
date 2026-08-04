import json
import re
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UNSAFE_CARD_MARKERS = ("<script", "javascript:", "{{", "delete_task", "create_task")
MAX_COMPACT_CARD_CHARS = 12000


def _validate_card_content(parts: list[str], extensions: dict[str, Any]) -> None:
    extension_text = json.dumps(extensions, ensure_ascii=False, sort_keys=True)
    combined = "\n".join([*parts, extension_text]).lower()
    if len(combined) > MAX_COMPACT_CARD_CHARS:
        raise ValueError("角色卡内容超过精简格式限制")
    if any(marker in combined for marker in UNSAFE_CARD_MARKERS):
        raise ValueError("角色卡包含当前版本不支持的宏、脚本或工具指令")


class RoleCardSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str
    personality: str
    speaking_style: str
    creator: str
    version: str
    is_builtin: bool


class RoleCardDetail(RoleCardSummary):
    system_prompt: str
    example_messages: list[str]
    extensions: dict[str, Any]
    is_active: bool


class ReminderPreferenceResponse(BaseModel):
    enabled: bool
    language: str
    timezone: str
    cadence_offsets: list[int]
    daily_dispatch_time: str
    default_task_reminder_offsets_minutes: list[int]
    email_enabled: bool
    chat_enabled: bool
    role_card: Optional[RoleCardSummary]


class ReminderPreferenceUpdate(BaseModel):
    enabled: Optional[bool] = None
    language: Optional[str] = Field(default=None, min_length=2, max_length=35)
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=64)
    cadence_offsets: Optional[list[int]] = Field(
        default=None,
        max_length=371,
        description=(
            "完整提醒档位集合；必须保留基础档位，且可额外添加 "
            "D+2 至 D+365（用 -2 至 -365 表示）"
        ),
    )
    daily_dispatch_time: Optional[str] = Field(default=None, max_length=5)
    default_task_reminder_offsets_minutes: Optional[list[int]] = Field(
        default=None, max_length=10
    )
    email_enabled: Optional[bool] = None
    chat_enabled: Optional[bool] = None
    role_card_id: Optional[int] = None


class RoleCardCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    personality: str = Field(default="", max_length=2000)
    speaking_style: str = Field(default="", max_length=2000)
    system_prompt: str = Field(default="", max_length=2000)
    example_messages: list[str] = Field(default_factory=list, max_length=10)
    creator: str = Field(default="IB Deadline Assistant", max_length=120)
    version: str = Field(default="1.0", max_length=30)
    extensions: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not SLUG_RE.fullmatch(value):
            raise ValueError("slug 只能使用小写字母、数字和连字符")
        return value

    @model_validator(mode="after")
    def reject_unsafe_prompt_content(self):
        _validate_card_content(
            [
                self.description,
                self.personality,
                self.speaking_style,
                self.system_prompt,
                *self.example_messages,
            ],
            self.extensions,
        )
        return self


class RoleCardUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    personality: Optional[str] = Field(default=None, max_length=2000)
    speaking_style: Optional[str] = Field(default=None, max_length=2000)
    system_prompt: Optional[str] = Field(default=None, max_length=2000)
    example_messages: Optional[list[str]] = Field(default=None, max_length=10)
    creator: Optional[str] = Field(default=None, max_length=120)
    version: Optional[str] = Field(default=None, max_length=30)
    extensions: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def reject_unsafe_prompt_content(self):
        values = [
            self.description or "",
            self.personality or "",
            self.speaking_style or "",
            self.system_prompt or "",
            *(self.example_messages or []),
        ]
        _validate_card_content(values, self.extensions or {})
        return self


class DeliveryHistoryItem(BaseModel):
    channel: str
    status: str
    attempt_count: int
    last_error_code: Optional[str]
    delivered_at: Optional[datetime]


class ReminderHistoryItem(BaseModel):
    id: int
    local_date: date
    subject: Optional[str]
    body_text: Optional[str]
    generation_mode: Optional[str]
    role_card_id: Optional[int]
    item_snapshot: list[dict[str, Any]]
    created_at: datetime
    deliveries: list[DeliveryHistoryItem]


class ReminderHistoryResponse(BaseModel):
    items: list[ReminderHistoryItem]
    limit: int
    offset: int


class ManualReminderRunRequest(BaseModel):
    evaluation_time: Optional[datetime] = None
    user_id: Optional[int] = None
    deliver: bool = False

    @field_validator("evaluation_time")
    @classmethod
    def timezone_required(cls, value: Optional[datetime]):
        if value is not None and value.tzinfo is None:
            raise ValueError("evaluation_time 必须包含时区")
        return value


class ReminderRunResponse(BaseModel):
    evaluated_users: int
    due_users: int
    candidate_items: int
    generated_digests: int
    delivered_channels: int
    failed_channels: int
    dry_run: bool
