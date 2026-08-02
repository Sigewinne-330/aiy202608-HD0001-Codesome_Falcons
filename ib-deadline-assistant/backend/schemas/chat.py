from pydantic import BaseModel
from datetime import datetime, date
from typing import List, Optional


class ChatMessage(BaseModel):
    content: str


class ChatResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatHistoryResponse(BaseModel):
    messages: List[ChatResponse]


# ---- 从聊天中提取并保存任务 ----

class ChatSubTaskItem(BaseModel):
    """AI 拆解出的单个子任务"""
    name: str                          # 子任务名称
    description: Optional[str] = ""    # 描述
    notice_time: Optional[str] = None  # 截止日期 YYYY-MM-DD
    level: str = "medium"              # 优先级 low/medium/high/urgent
    estimated_hours: float = 0         # 预估小时数


class ChatTaskSave(BaseModel):
    """从聊天中保存任务的请求体"""
    title: str                         # 父任务标题
    description: Optional[str] = ""
    subject: Optional[str] = None      # 科目
    deadline: Optional[str] = None     # 截止日期 YYYY-MM-DD
    priority: str = "medium"           # 优先级
    subtasks: List[ChatSubTaskItem] = []
