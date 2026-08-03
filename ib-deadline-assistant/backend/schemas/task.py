from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional, List


class TaskCreate(BaseModel):
    task_type: str = "todo"
    title: str
    description: Optional[str] = None
    subject: Optional[str] = None
    category: Optional[str] = None
    priority: str = "medium"
    deadline: Optional[date] = None
    estimated_hours: Optional[float] = 0


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    subject: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[date] = None
    estimated_hours: Optional[float] = None
    progress: Optional[int] = None


class TaskResponse(BaseModel):
    id: int
    user_id: int
    task_type: str = "todo"
    title: str
    description: Optional[str] = None
    subject: Optional[str] = None
    category: Optional[str] = None
    priority: str
    status: str
    deadline: Optional[date] = None
    estimated_hours: float
    progress: int
    created_at: datetime
    update_time: Optional[datetime] = None
    subtasks: List["TaskResponse"] = Field(default_factory=list)
    sub_task_source: bool = False  # True 表示该记录来自 sub_task 表

    class Config:
        from_attributes = True


class SubTaskCreate(BaseModel):
    task_id: int
    name: str
    description: Optional[str] = ""
    notice_time: Optional[date] = None
    level: str = "medium"
    status: str = "pending"


class SubTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    notice_time: Optional[date] = None
    level: Optional[str] = None
    status: Optional[str] = None


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
