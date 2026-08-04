from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional


class DeadlineCreate(BaseModel):
    source: Optional[str] = None
    title: str
    description: Optional[str] = None
    due_date: date
    subject: Optional[str] = None
    priority: str = "medium"
    estimated_hours: Optional[float] = Field(default=None, ge=0, le=24)
    energy_intensity: float = Field(default=1.0, ge=0.5, le=2.0)
    effort_source: str = "user"
    is_schedule_locked: bool = True
    schedule_kind: Optional[str] = None


class DeadlineUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    subject: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    estimated_hours: Optional[float] = Field(default=None, ge=0, le=24)
    energy_intensity: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    effort_source: Optional[str] = None
    is_schedule_locked: Optional[bool] = None
    schedule_kind: Optional[str] = None


class DeadlineResponse(BaseModel):
    id: int
    user_id: int
    source: Optional[str] = None
    title: str
    description: Optional[str] = None
    due_date: date
    subject: Optional[str] = None
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime
    estimated_hours: Optional[float] = None
    energy_intensity: float = 1.0
    effort_source: str = "default"
    is_schedule_locked: bool = True
    schedule_version: int = 1
    schedule_kind: Optional[str] = None

    class Config:
        from_attributes = True


class CollisionCheckRequest(BaseModel):
    date: date
