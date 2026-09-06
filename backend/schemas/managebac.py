from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ManageBacFeedRequest(BaseModel):
    feed_url: str = Field(min_length=20, max_length=4096)

    @field_validator("feed_url")
    @classmethod
    def trim_feed_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("iCal 地址不能为空")
        return value


class ManageBacPreviewItem(BaseModel):
    title: str
    subject: Optional[str] = None
    deadline: datetime
    kind: str


class ManageBacValidationResponse(BaseModel):
    valid: bool = True
    feed_host: str
    calendar_name: Optional[str] = None
    total_items: int
    importable_items: int
    skipped_items: int
    preview: list[ManageBacPreviewItem] = Field(default_factory=list)


class ManageBacConnectionSettings(BaseModel):
    enabled: bool


class ManageBacConnectionStatus(BaseModel):
    connected: bool
    status: Optional[str] = None
    enabled: bool = False
    feed_host: Optional[str] = None
    sync_interval_minutes: int = 10
    next_sync_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    consecutive_failures: int = 0
    last_error_code: Optional[str] = None
    last_error_detail: Optional[str] = None


class ManageBacSyncSummary(BaseModel):
    status: str
    http_status: Optional[int] = None
    total_items: int = 0
    added_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    cancelled_count: int = 0
    skipped_count: int = 0
    error_code: Optional[str] = None


class ManageBacConnectResponse(BaseModel):
    connection: ManageBacConnectionStatus
    validation: ManageBacValidationResponse
    sync: ManageBacSyncSummary


class ManageBacSyncRunResponse(ManageBacSyncSummary):
    id: int
    trigger: Literal["automatic", "manual", "initial"]
    started_at: datetime
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ManageBacSyncRunsResponse(BaseModel):
    items: list[ManageBacSyncRunResponse]


class ManageBacDisconnectResponse(BaseModel):
    disconnected: bool = True
    deleted_tasks: int = 0
