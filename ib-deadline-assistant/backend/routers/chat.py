"""Chat router — 支持 OpenAI function calling 的 AI 对话端点

核心流程：
  用户消息 → 构建 messages（system + history + user）
    → 调 AI（带 tools）
    → 如果 AI 返回 tool_calls → 执行工具 → 结果喂回 AI → 循环
    → AI 返回最终文本 → 保存到聊天历史 → 返回
"""
import json
import logging
from datetime import date
from typing import List, Dict, Any, AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from models.chat import ChatHistory as ChatHistoryModel, MessageRole
from schemas.chat import ChatMessage, ChatResponse, ChatHistoryResponse
from services.auth import get_current_user
from services.ai_service import ai_service, SYSTEM_PROMPT
from services.task_tools_schema import TASK_TOOLS
from services import task_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 最大工具调用轮次，防止无限循环
MAX_TOOL_ROUNDS = 30

# 工具名 → 执行函数的映射
TOOL_DISPATCH: Dict[str, Any] = {
    "create_task": task_tools.create_task,
    "list_tasks": task_tools.list_tasks,
    "delete_task": task_tools.delete_task,
    "create_subtask": task_tools.create_subtask,
    "list_subtasks": task_tools.list_subtasks,
    "delete_subtask": task_tools.delete_subtask,
}


def _with_date_prefix(user_message: str) -> str:
    """在用户消息前添加当前日期，帮助 AI 理解相对时间（如"今天"、"下周"）"""
    today = date.today().isoformat()  # YYYY-MM-DD
    return f"[当前日期：{today}]\n\n{user_message}"


def _build_messages(
    user_message: str,
    history: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """构建带 system prompt 的完整消息列表，用户消息自动附加当前日期"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": _with_date_prefix(user_message)},
    ]


async def _run_tool_loop(
    messages: List[Dict[str, Any]],
    db: Session,
    user_id: int,
) -> str:
    """执行工具调用循环：调 AI → 执行工具 → 喂回结果 → 重复，直到 AI 返回最终文本。

    Args:
        messages: 初始消息列表（已含 system + history + user）
        db: 数据库会话
        user_id: 当前用户 ID

    Returns:
        AI 的最终文本回复
    """
    for _round in range(MAX_TOOL_ROUNDS):
        choice = await ai_service.chat_with_tools(messages, TASK_TOOLS)

        # AI 要求调用工具
        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            assistant_msg = choice.message.model_dump()
            messages.append(assistant_msg)

            for tc in choice.message.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                logger.info(f"Tool call: {func_name}({func_args})")

                # 执行工具函数
                handler = TOOL_DISPATCH.get(func_name)
                if handler:
                    try:
                        result = handler(db=db, user_id=user_id, **func_args)
                    except Exception as e:
                        result = {"error": f"工具执行失败: {e}"}
                        logger.error(f"Tool {func_name} execution error: {e}")
                else:
                    result = {"error": f"未知工具: {func_name}"}

                # 把工具结果追加到对话
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            continue  # 继续下一轮，让 AI 基于工具结果生成回复

        # AI 返回了最终文本
        return choice.message.content or ""

    # 超过最大轮次
    return "抱歉，处理过程中超过了最大工具调用次数，请简化你的请求后重试。"


async def _run_tool_loop_stream(
    messages: List[Dict[str, Any]],
    db: Session,
    user_id: int,
) -> AsyncGenerator[Dict[str, Any], None]:
    """流式工具调用循环：边推文本边处理工具调用，工具执行时推送状态反馈。

    产出事件格式：
      {"type": "text", "content": "..."}   — 普通文本，可直接推前端
      {"type": "status", "content": "..."} — 状态提示（如"正在创建任务..."）
      {"type": "done", "content": "..."}   — 完整回复文本（用于保存）

    Args:
        messages: 初始消息列表
        db: 数据库会话
        user_id: 当前用户 ID
    """
    full_reply: List[str] = []  # 跨轮累积完整回复

    for _round in range(MAX_TOOL_ROUNDS):
        tool_calls = None

        async for event in ai_service.chat_stream_with_tools(messages, TASK_TOOLS):
            if event["type"] == "text":
                full_reply.append(event["content"])
                yield event  # 直接透传文本

            elif event["type"] == "tool_calls":
                tool_calls = event["tool_calls"]

        # 没有工具调用 → 纯文本对话完成
        if tool_calls is None:
            yield {"type": "done", "content": "".join(full_reply)}
            return

        # 有工具调用 → 推送状态 + 执行
        tool_names = [tc["function"]["name"] for tc in tool_calls]
        logger.info(f"Stream tool calls: {tool_names}")

        # 构建 assistant 消息（保存已流式输出的文本 + tool_calls）
        assistant_msg = {
            "role": "assistant",
            "content": "".join(full_reply) if full_reply else None,
            "tool_calls": tool_calls,
        }
        messages.append(assistant_msg)

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}

            # 状态反馈
            status_map = {
                "create_task": "正在创建任务...",
                "delete_task": "正在删除任务...",
                "create_subtask": "正在添加子任务...",
                "delete_subtask": "正在删除子任务...",
            }
            status = status_map.get(func_name, f"正在执行 {func_name}...")
            yield {"type": "status", "content": status}

            # 执行工具
            handler = TOOL_DISPATCH.get(func_name)
            if handler:
                try:
                    result = handler(db=db, user_id=user_id, **func_args)
                except Exception as e:
                    result = {"error": f"工具执行失败: {e}"}
                    logger.error(f"Tool {func_name} error: {e}")
            else:
                result = {"error": f"未知工具: {func_name}"}

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })

            # 工具执行完毕后推送结果状态
            if isinstance(result, list):
                count = len(result)
                yield {"type": "status", "content": f"✓ 找到 {count} 条记录"}
            elif isinstance(result, dict):
                if result.get("ok"):
                    yield {"type": "status", "content": "✓ 操作成功"}
                elif result.get("error"):
                    yield {"type": "status", "content": f"✗ {result['error']}"}
                elif result.get("id"):
                    yield {"type": "status", "content": "✓ 操作成功"}

        # 工具执行完，继续下一轮（AI 基于结果生成后续回复）
        full_reply = []  # 重置，因为后续回复是新一轮

    # 超过最大轮次
    yield {"type": "done", "content": "抱歉，处理过程中超过了最大工具调用次数，请简化你的请求后重试。"}


# ═══════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════

@router.post("", response_model=ChatResponse)
async def chat(
    data: ChatMessage,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """主对话端点 — 支持 Function Calling。

    当用户消息涉及任务管理（创建、查询、删除任务/子任务）时，
    AI 会自动调用对应工具操作数据库，然后基于结果生成自然语言回复。
    """
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

    # 构建消息并执行工具调用循环
    messages = _build_messages(data.content, history)
    reply = await _run_tool_loop(messages, db, current_user.id)

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


@router.post("/stream")
async def chat_stream(
    data: ChatMessage,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """流式对话 — 实时推送 AI 文本 + 工具调用状态反馈"""
    uid = current_user.id

    # 先保存用户消息
    user_msg = ChatHistoryModel(
        user_id=uid,
        role=MessageRole.user,
        content=data.content,
    )
    db.add(user_msg)
    db.commit()

    # 获取历史
    recent_history = (
        db.query(ChatHistoryModel)
        .filter(ChatHistoryModel.user_id == uid)
        .order_by(ChatHistoryModel.created_at.desc())
        .limit(20)
        .all()
    )
    recent_history.reverse()
    history = [
        {"role": h.role.value, "content": h.content}
        for h in recent_history
    ]

    # 构建消息
    messages = _build_messages(data.content, history)
    final_reply = ""  # 最终完整回复（用于保存到 chat_history）

    async def generate():
        nonlocal final_reply
        try:
            async for event in _run_tool_loop_stream(messages, db, uid):
                if event["type"] == "text":
                    yield f"data: {json.dumps(event['content'], ensure_ascii=False)}\n\n"

                elif event["type"] == "status":
                    status_text = f"[{event['content']}]"
                    yield f"data: {json.dumps(status_text, ensure_ascii=False)}\n\n"

                elif event["type"] == "done":
                    final_reply = event["content"]
                    yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            final_reply = f"错误：{e}"
        finally:
            if final_reply:
                from database import SessionLocal
                save_db = SessionLocal()
                try:
                    assistant_msg = ChatHistoryModel(
                        user_id=uid,
                        role=MessageRole.assistant,
                        content=final_reply,
                    )
                    save_db.add(assistant_msg)
                    save_db.commit()
                finally:
                    save_db.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tools")
def list_tools(current_user: User = Depends(get_current_user)):
    """列出所有可用工具（供前端调试/展示）"""
    tool_names = [
        {"name": t["function"]["name"], "description": t["function"]["description"]}
        for t in TASK_TOOLS
    ]
    return {"count": len(tool_names), "tools": tool_names}


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
