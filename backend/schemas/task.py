from pydantic import BaseModel, Field, field_validator
from datetime import date, datetime
from typing import Optional, List
from models.task_new import TaskCategory


class TaskCreate(BaseModel):
    task_type: str = "todo"
    title: str
    description: Optional[str] = None
    subject: Optional[str] = None
    category: Optional[TaskCategory] = None
    priority: str = "medium"
    deadline: Optional[datetime] = None
    reminder_offsets_minutes: Optional[List[int]] = Field(default=None, max_length=10)
    estimated_hours: Optional[float] = 0
    earliest_start_date: Optional[date] = None
    hard_deadline_date: Optional[date] = None
    energy_intensity: float = Field(default=1.0, ge=0.5, le=2.0)
    effort_source: str = "user"
    is_schedule_locked: bool = False
    schedule_kind: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    subject: Optional[str] = None
    category: Optional[TaskCategory] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[datetime] = None
    reminder_offsets_minutes: Optional[List[int]] = Field(default=None, max_length=10)
    estimated_hours: Optional[float] = None
    progress: Optional[int] = None
    earliest_start_date: Optional[date] = None
    hard_deadline_date: Optional[date] = None
    energy_intensity: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    effort_source: Optional[str] = None
    is_schedule_locked: Optional[bool] = None
    schedule_kind: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    user_id: int
    task_type: str = "todo"
    title: str
    description: Optional[str] = None
    subject: Optional[str] = None
    category: Optional[TaskCategory] = None
    priority: str
    status: str
    # Keep the legacy date-only response shape for the current frontend.  The
    # write schemas accept DateTime so later settings UI can use exact minutes.
    deadline: Optional[date] = None
    reminder_offsets_minutes: Optional[List[int]] = None
    estimated_hours: float
    progress: int
    created_at: datetime
    update_time: Optional[datetime] = None
    subtasks: List["TaskResponse"] = Field(default_factory=list)
    sub_task_source: bool = False  # True 表示该记录来自 sub_task 表
    earliest_start_date: Optional[date] = None
    hard_deadline_date: Optional[date] = None
    energy_intensity: float = 1.0
    effort_source: str = "default"
    is_schedule_locked: bool = False
    schedule_version: int = 1
    schedule_kind: Optional[str] = None

    class Config:
        from_attributes = True

    @field_validator("deadline", mode="before")
    @classmethod
    def keep_legacy_date_shape(cls, value):
        return value.date() if isinstance(value, datetime) else value


class SubTaskCreate(BaseModel):
    task_id: int
    name: str
    description: Optional[str] = ""
    notice_time: Optional[date] = None
    level: str = "medium"
    status: str = "pending"
    estimated_hours: float = Field(default=0, ge=0, le=24)
    earliest_start_date: Optional[date] = None
    hard_deadline_date: Optional[date] = None
    energy_intensity: float = Field(default=1.0, ge=0.5, le=2.0)
    effort_source: str = "user"
    is_schedule_locked: bool = False
    schedule_kind: Optional[str] = None


class SubTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    notice_time: Optional[date] = None
    level: Optional[str] = None
    status: Optional[str] = None
    estimated_hours: Optional[float] = Field(default=None, ge=0, le=24)
    earliest_start_date: Optional[date] = None
    hard_deadline_date: Optional[date] = None
    energy_intensity: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    effort_source: Optional[str] = None
    is_schedule_locked: Optional[bool] = None
    schedule_kind: Optional[str] = None


class TaskBreakdownRequest(BaseModel):
    task_id: int


class TaskPlanRequest(BaseModel):
    """任务规划请求"""
    title: str
    word_count: int = 0
    deadline: str  # YYYY-MM-DD
    description: Optional[str] = ""


class TaskPlanPhase(BaseModel):
    """任务规划 - 单个阶段"""
    phase: str
    description: str
    start_date: str
    end_date: str
    estimated_hours: int
    priority: str
    deliverables: str


class TaskPlanResponse(BaseModel):
    """任务规划响应"""
    title: str
    word_count: int
    deadline: str
    phases: List[TaskPlanPhase]
    total_hours: int
    total_days: int
