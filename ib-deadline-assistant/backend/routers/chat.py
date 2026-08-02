import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
from datetime import date
from database import get_db
from models.user import User
from models.task import Task as TaskModel, Priority, TaskStatus
from models.sub_task import SubTask as SubTaskModel
from models.chat import ChatHistory as ChatHistoryModel, MessageRole
from schemas.chat import ChatMessage, ChatResponse, ChatHistoryResponse, ChatTaskSave
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
                # JSON 编码：chunk 内的换行等特殊字符会被转义，不破坏 SSE 帧结构
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
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


@router.post("/save-tasks")
def save_tasks_from_chat(
    data: ChatTaskSave,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从聊天中提取的任务数据，一键创建父任务 + 子任务并写入 sub_tasks 表"""
    # 解析截止日期
    try:
        task_deadline = date.fromisoformat(data.deadline) if data.deadline else None
    except ValueError:
        task_deadline = None

    # 创建父任务
    parent_task = TaskModel(
        user_id=current_user.id,
        title=data.title,
        description=data.description or "",
        subject=data.subject,
        priority=Priority(data.priority) if data.priority in [e.value for e in Priority] else Priority.medium,
        deadline=task_deadline,
        estimated_hours=sum(st.estimated_hours for st in data.subtasks),
        status=TaskStatus.todo,
    )
    db.add(parent_task)
    db.flush()  # 获取 parent_task.id

    # 创建子任务（写入 sub_tasks 表）
    created_subtasks = []
    for st in data.subtasks:
        try:
            notice = date.fromisoformat(st.notice_time) if st.notice_time else None
        except ValueError:
            notice = None

        sub = SubTaskModel(
            task_id=parent_task.id,
            name=st.name,
            description=st.description or "",
            notice_time=notice,
            level=Priority(st.level) if st.level in [e.value for e in Priority] else Priority.medium,
            status=TaskStatus.todo,
        )
        db.add(sub)
        created_subtasks.append({
            "id": None,  # commit 后才能拿到 id
            "name": st.name,
            "notice_time": st.notice_time,
            "level": st.level,
        })

    db.commit()
    db.refresh(parent_task)

    # 拿回子任务 id
    saved_subs = db.query(SubTaskModel).filter(
        SubTaskModel.task_id == parent_task.id
    ).all()
    for i, s in enumerate(saved_subs):
        if i < len(created_subtasks):
            created_subtasks[i]["id"] = s.id

    return {
        "ok": True,
        "task_id": parent_task.id,
        "task_title": parent_task.title,
        "subtask_count": len(saved_subs),
        "subtasks": created_subtasks,
    }
