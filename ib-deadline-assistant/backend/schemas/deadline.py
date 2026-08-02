from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional


class DeadlineCreate(BaseModel):
    source: Optional[str] = None
    title: str
    description: Optional[str] = None
    due_date: date
    subject: Optional[str] = None
    priority: str = "medium"


class DeadlineUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    subject: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None


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

    class Config:
        from_attributes = True


class CollisionCheckRequest(BaseModel):
    date: date
