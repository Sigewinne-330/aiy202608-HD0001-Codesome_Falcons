from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models.user import User
from models.chat import ChatHistory as ChatHistoryModel, MessageRole
from schemas.chat import ChatMessage, ChatResponse, ChatHistoryResponse
from services.auth import get_current_user
from services.ai_service import ai_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(
    data: ChatMessage,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """流式对话 — SSE 格式逐字返回 AI 回复"""
    # 获取历史
    recent_history = (
        db.query(ChatHistoryModel)
        .filter(ChatHistoryModel.user_id == current_user.id)
        .order_by(ChatHistoryModel.created_at.desc())
        .limit(20)
        .all()
    )
    recent_history.reverse()
    history = [
        {"role": h.role.value, "content": h.content}
        for h in recent_history
    ]

    # 先保存用户消息
    user_msg = ChatHistoryModel(
        user_id=current_user.id,
        role=MessageRole.user,
        content=data.content,
    )
    db.add(user_msg)
    db.commit()

    async def generate():
        full_content = ""
        try:
            async for chunk in ai_service.chat_stream(data.content, history):
                full_content += chunk
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"
        finally:
            # 保存完整 AI 回复
            if full_content:
                assistant_msg = ChatHistoryModel(
                    user_id=current_user.id,
                    role=MessageRole.assistant,
                    content=full_content,
                )
                db.add(assistant_msg)
                db.commit()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_model=ChatResponse)
async def chat(
    data: ChatMessage,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发送消息给 AI 助手"""
    # 获取最近 20 条历史记录
    recent_history = (
        db.query(ChatHistoryModel)
        .filter(ChatHistoryModel.user_id == current_user.id)
        .order_by(ChatHistoryModel.created_at.desc())
        .limit(20)
        .all()
    )
    recent_history.reverse()

    history = [
        {"role": h.role.value, "content": h.content}
        for h in recent_history
    ]

    # 调用 AI
    reply = await ai_service.chat(data.content, history)

    # 保存用户消息
    user_msg = ChatHistoryModel(
        user_id=current_user.id,
        role=MessageRole.user,
        content=data.content,
    )
    db.add(user_msg)

    # 保存 AI 回复
    assistant_msg = ChatHistoryModel(
        user_id=current_user.id,
        role=MessageRole.assistant,
        content=reply,
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    return ChatResponse.model_validate(assistant_msg)


@router.get("/history", response_model=ChatHistoryResponse)
def get_history(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取聊天历史"""
    messages = (
        db.query(ChatHistoryModel)
        .filter(ChatHistoryModel.user_id == current_user.id)
        .order_by(ChatHistoryModel.created_at.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()
    return ChatHistoryResponse(
        messages=[ChatResponse.model_validate(m) for m in messages]
    )


@router.delete("/history")
def clear_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """清空聊天历史"""
    db.query(ChatHistoryModel).filter(
        ChatHistoryModel.user_id == current_user.id
    ).delete()
    db.commit()
    return {"ok": True}
