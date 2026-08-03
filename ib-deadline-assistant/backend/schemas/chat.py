from pydantic import BaseModel
from datetime import datetime, date
from typing import List, Optional


class ChatMessage(BaseModel):
    """单条消息请求。conversation_id 不传时自动新建对话。images 为 base64 data URL 列表（最多 5 张）。"""
    content: str
    conversation_id: Optional[int] = None
    images: Optional[List[str]] = None  # data:image/...;base64,...


class ChatResponse(BaseModel):
    """单条消息响应（对应 chat_message 表）"""
    id: int
    conversation_id: int
    role: str
    content: str
    token: Optional[int] = 0
    update_time: datetime

    class Config:
        from_attributes = True


class ChatHistoryResponse(BaseModel):
    """某个对话的消息列表"""
    conversation_id: int
    messages: List[ChatResponse]


class ConversationResponse(BaseModel):
    """对话窗口（对应 conversation 表）"""
    id: int
    title: Optional[str] = None
    update_time: datetime

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    """对话列表"""
    conversations: List[ConversationResponse]


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
