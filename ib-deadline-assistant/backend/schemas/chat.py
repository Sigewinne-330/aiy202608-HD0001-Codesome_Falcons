from pydantic import BaseModel
from datetime import datetime
from typing import List


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
