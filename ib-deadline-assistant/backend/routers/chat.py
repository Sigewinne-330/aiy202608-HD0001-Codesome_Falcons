"""Chat router — 支持 OpenAI function calling 的 AI 对话端点（conversation + chat_message 新表体系）

表结构：
  conversation   = 对话窗口（一条对话记录）
  chat_message   = 对话窗口里的一条条消息（role: user / assistant）

核心流程：
  用户消息 → 获取/新建对话(conversation) → 构建 messages（system + history + user）
    → 调 AI（带 tools）
    → 如果 AI 返回 tool_calls → 执行工具 → 结果喂回 AI → 循环
    → AI 返回最终文本 → 保存到 chat_message → 返回
"""
import json
import logging
from datetime import date
from typing import List, Dict, Any, AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models.app_user import AppUser as User
from models.conversation import Conversation
from models.chat_message_new import ChatMessage as ChatMessageModel
from schemas.chat import (
    ChatMessage, ChatResponse, ChatHistoryResponse,
    ConversationResponse, ConversationListResponse,
)
from services.auth import get_current_user
from services.ai_service import ai_service, SYSTEM_PROMPT
from services.main_agent_role_cards import prepare_main_agent_role_context
from services.task_tools_schema import TASK_TOOLS
from services.knowledge_base_tools import KNOWLEDGE_BASE_TOOLS, get_subject_guidelines
from services import task_tools
from services.billing import ensure_balance, deduct_credits, credits_for_tokens
from services.image_storage import save_images

# 合并所有可用工具（任务 CRUD + 知识库查询）
ALL_TOOLS = TASK_TOOLS + KNOWLEDGE_BASE_TOOLS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 最大工具调用轮次，防止无限循环
MAX_TOOL_ROUNDS = 30

# 工具名 → 执行函数的映射
TOOL_DISPATCH: Dict[str, Any] = {
    "create_task": task_tools.create_task,
    "list_tasks": task_tools.list_tasks,
    "update_task": task_tools.update_task,
    "delete_task": task_tools.delete_task,
    "create_subtask": task_tools.create_subtask,
    "list_subtasks": task_tools.list_subtasks,
    "update_subtask": task_tools.update_subtask,
    "delete_subtask": task_tools.delete_subtask,
    "get_subject_guidelines": get_subject_guidelines,
}


def _get_or_create_conversation(
    db: Session,
    user_id: int,
    conversation_id: Optional[int] = None,
    first_message: str = "",
) -> Conversation:
    """获取指定对话；未指定时自动新建一个对话窗口。"""
    if conversation_id:
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .first()
        )
        if conv:
            return conv
        raise HTTPException(status_code=404, detail="对话不存在或无权访问")

    # 新建对话：标题取第一条消息的前 30 字
    title = first_message[:30] if first_message else "新对话"
    conv = Conversation(user_id=user_id, title=title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _with_date_prefix(user_message: str) -> str:
    """在用户消息前添加当前日期，帮助 AI 理解相对时间（如"今天"、"下周"）"""
    today = date.today().isoformat()  # YYYY-MM-DD
    return f"[当前日期：{today}]\n\n{user_message}"


def _build_messages(
    user_message: str,
    history: List[Dict[str, str]],
    images: Optional[List[str]] = None,
    system_prompt: str = SYSTEM_PROMPT,
) -> List[Dict[str, Any]]:
    """构建带 system prompt 的完整消息列表。

    当 images 非空时，用户消息使用多模态格式（text + image_url），
    否则使用纯文本格式。
    """
    if images:
        content_parts: List[Dict[str, Any]] = [
            {"type": "text", "text": _with_date_prefix(user_message)},
        ]
        for img in images[:5]:  # 最多 5 张
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": img},
            })
        user_content: Any = content_parts
    else:
        user_content = _with_date_prefix(user_message)

    return [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_content},
    ]


def _load_history(db: Session, conversation_id: int, limit: int = 20) -> List[Dict[str, str]]:
    """加载某个对话窗口最近的消息（按时间升序返回，供 AI 上下文使用）"""
    recent = (
        db.query(ChatMessageModel)
        .filter(ChatMessageModel.conversation_id == conversation_id)
        .order_by(ChatMessageModel.update_time.desc())
        .limit(limit)
        .all()
    )
    recent.reverse()
    return [{"role": m.role, "content": m.content} for m in recent]


async def _run_tool_loop(
    messages: List[Dict[str, Any]],
    db: Session,
    user_id: int,
    usage_tracker: Optional[Dict[str, int]] = None,
) -> str:
    """执行工具调用循环：调 AI → 执行工具 → 喂回结果 → 重复，直到 AI 返回最终文本。

    Args:
        messages: 初始消息列表（已含 system + history + user）
        db: 数据库会话
        user_id: 当前用户 ID
        usage_tracker: 可选 dict，累计每轮真实 token 用量（{"total_tokens": int}）

    Returns:
        AI 的最终文本回复
    """
    for _round in range(MAX_TOOL_ROUNDS):
        choice = await ai_service.chat_with_tools(messages, ALL_TOOLS)

        # 累计本轮 token 用量（用于计费）
        if usage_tracker is not None and choice.usage and getattr(choice.usage, "total_tokens", None):
            usage_tracker["total_tokens"] = usage_tracker.get("total_tokens", 0) + choice.usage.total_tokens

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
    has_images: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """流式工具调用循环：边推文本边处理工具调用，工具执行时推送状态反馈。

    当 has_images=True 时，首轮使用多模态模型（支持图片输入），
    工具执行完毕后自动将图片从用户消息中剥离，后续轮次切回常规模型。

    产出事件格式：
      {"type": "text", "content": "..."}   — 普通文本，可直接推前端
      {"type": "status", "content": "..."} — 状态提示（如"正在创建任务..."）
      {"type": "done", "content": "..."}   — 完整回复文本（用于保存）
    """
    full_reply: List[str] = []  # 跨轮累积完整回复
    use_vision = has_images

    for _round in range(MAX_TOOL_ROUNDS):
        tool_calls = None

        # 选择模型：首轮有图片 → 多模态模型；后续 → 常规模型
        if use_vision:
            stream_gen = ai_service.chat_stream_with_tools_vision(messages, ALL_TOOLS)
        else:
            stream_gen = ai_service.chat_stream_with_tools(messages, ALL_TOOLS)

        async for event in stream_gen:
            if event["type"] == "text":
                full_reply.append(event["content"])
                yield event

            elif event["type"] == "usage":
                yield event  # 透传本轮 token 用量（计费用）

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
                "get_subject_guidelines": "正在查阅知识库...",
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
                if result.get("ok") and result.get("subject"):
                    content_len = len(result.get("content", ""))
                    yield {"type": "status", "content": f"✓ 已加载 {result['subject']} 指南 ({content_len:,} 字符)"}
                elif result.get("ok"):
                    yield {"type": "status", "content": "✓ 操作成功"}
                elif result.get("error"):
                    yield {"type": "status", "content": f"✗ {result['error']}"}

        # 首轮（多模态）结束后：将图片从用户消息中剥离，后续切回常规模型
        if use_vision:
            use_vision = False
            for msg in messages:
                if msg["role"] == "user" and isinstance(msg.get("content"), list):
                    # 只保留文本部分
                    text_parts = [
                        part["text"] for part in msg["content"]
                        if part.get("type") == "text"
                    ]
                    msg["content"] = "".join(text_parts) if text_parts else msg["content"]

        # 工具执行完，继续下一轮
        full_reply = []  # 重置，因为后续回复是新一轮

    # 超过最大轮次
    yield {"type": "done", "content": "抱歉，处理过程中超过了最大工具调用次数，请简化你的请求后重试。"}


# ═══════════════════════════════════════════════════════════════
# 对话窗口（conversation）管理
# ═══════════════════════════════════════════════════════════════

@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的全部对话窗口（按更新时间倒序）"""
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.update_time.desc())
        .all()
    )
    return ConversationListResponse(conversations=conversations)


@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新建一个空的对话窗口"""
    conv = Conversation(user_id=current_user.id, title="新对话")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除对话窗口及其全部消息（chat_message 外键级联删除）"""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == current_user.id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在或无权访问")
    db.delete(conv)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# 对话消息（chat_message）
# ═══════════════════════════════════════════════════════════════

@router.post("", response_model=ChatResponse)
async def chat(
    data: ChatMessage,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """主对话端点 — 支持 Function Calling。

    conversation_id 不传时自动新建对话窗口。
    用户消息与 AI 回复均作为 chat_message 保存。
    """
    # 计费：发送前检查余额
    ensure_balance(current_user)

    # 获取或新建对话窗口
    conv = _get_or_create_conversation(
        db, current_user.id, data.conversation_id, first_message=data.content
    )

    # 加载该对话窗口最近的历史（作为 AI 上下文）
    history = _load_history(db, conv.id, limit=20)

    # 构建消息并执行工具调用循环。角色卡只影响本次请求的表达风格。
    role_context = prepare_main_agent_role_context(
        db, current_user.id, SYSTEM_PROMPT
    )
    messages = _build_messages(
        data.content,
        history,
        images=data.images,
        system_prompt=role_context.system_prompt,
    )
    usage_tracker: Dict[str, int] = {}
    reply = await _run_tool_loop(messages, db, current_user.id, usage_tracker)

    # 保存用户消息（图片落盘为文件，extra 只存 URL，历史记录永久保留）
    user_msg = ChatMessageModel(
        user_id=current_user.id,
        conversation_id=conv.id,
        role="user",
        content=data.content,
        token=0,
        extra={"images": save_images(data.images)} if data.images else None,
    )
    db.add(user_msg)

    # 保存 AI 回复
    total_tokens = usage_tracker.get("total_tokens", 0)
    assistant_msg = ChatMessageModel(
        user_id=current_user.id,
        conversation_id=conv.id,
        role="assistant",
        content=reply,
        token=total_tokens,
        extra=role_context.message_metadata,
    )
    db.add(assistant_msg)
    db.flush()  # 拿到 assistant_msg.id 用于流水关联

    # 计费：按实际 token 扣积分并写流水（ref 关联本条 AI 回复）
    deduct_credits(db, current_user, total_tokens, ref_id=assistant_msg.id, note=f"AI 对话消耗 {total_tokens} tokens")

    # 更新对话标题（未设置时用第一条用户消息）
    if not conv.title or conv.title == "新对话":
        conv.title = data.content[:30]
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
    # 计费：发送前检查余额
    ensure_balance(current_user)

    conv = _get_or_create_conversation(
        db, uid, data.conversation_id, first_message=data.content
    )

    # 先保存用户消息（图片落盘为文件，extra 只存 URL，历史记录永久保留）
    user_msg = ChatMessageModel(
        user_id=uid,
        conversation_id=conv.id,
        role="user",
        content=data.content,
        token=0,
        extra={"images": save_images(data.images)} if data.images else None,
    )
    db.add(user_msg)
    db.commit()

    # 加载该对话窗口历史
    history = _load_history(db, conv.id, limit=20)

    # 构建消息；在流开始前固定角色快照，避免中途切换造成审计漂移。
    role_context = prepare_main_agent_role_context(db, uid, SYSTEM_PROMPT)
    has_images = bool(data.images)
    messages = _build_messages(
        data.content,
        history,
        images=data.images,
        system_prompt=role_context.system_prompt,
    )
    final_reply = ""  # 最终完整回复（用于保存到 chat_message）
    total_tokens = 0  # 本轮真实 token 用量（用于计费）

    async def generate():
        nonlocal final_reply, total_tokens
        try:
            async for event in _run_tool_loop_stream(messages, db, uid, has_images=has_images):
                if event["type"] == "text":
                    yield f"data: {json.dumps(event['content'], ensure_ascii=False)}\n\n"

                elif event["type"] == "usage":
                    # 累计多轮工具调用的 token 用量
                    total_tokens += (event.get("usage") or {}).get("total_tokens", 0)

                elif event["type"] == "status":
                    status_text = f"[{event['content']}]"
                    yield f"data: {json.dumps(status_text, ensure_ascii=False)}\n\n"

                elif event["type"] == "done":
                    final_reply = event["content"]
                    # 下发本轮真实 token 与换算后的积分（前端用于展示，credits 为权威值）
                    yield f"data: {json.dumps({'done': True, 'tokens': total_tokens, 'credits': credits_for_tokens(total_tokens)}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            final_reply = f"错误：{e}"
        finally:
            if final_reply:
                from database import SessionLocal
                save_db = SessionLocal()
                try:
                    # 更新对话标题（未设置时用第一条用户消息）
                    conv2 = save_db.query(Conversation).filter(Conversation.id == conv.id).first()
                    if conv2 and (not conv2.title or conv2.title == "新对话"):
                        conv2.title = data.content[:30]

                    assistant_msg = ChatMessageModel(
                        user_id=uid,
                        conversation_id=conv.id,
                        role="assistant",
                        content=final_reply,
                        token=total_tokens,
                        extra=role_context.message_metadata,
                    )
                    save_db.add(assistant_msg)
                    save_db.flush()  # 拿到 assistant_msg.id 用于流水关联

                    # 计费：按实际 token 扣积分并写流水
                    user2 = save_db.query(User).filter(User.id == uid).first()
                    if user2:
                        deduct_credits(save_db, user2, total_tokens, ref_id=assistant_msg.id, note=f"AI 对话消耗 {total_tokens} tokens")

                    save_db.commit()
                except HTTPException:
                    # 余额不足等计费异常：回滚本次写入，保证不欠费
                    save_db.rollback()
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
        for t in ALL_TOOLS
    ]
    return {"count": len(tool_names), "tools": tool_names}


@router.get("/history", response_model=ChatHistoryResponse)
def get_history(
    conversation_id: int,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取某个对话窗口的消息列表（按时间升序）"""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == current_user.id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在或无权访问")

    messages = (
        db.query(ChatMessageModel)
        .filter(ChatMessageModel.conversation_id == conv.id)
        .order_by(ChatMessageModel.update_time.asc())
        .limit(limit)
        .all()
    )
    return ChatHistoryResponse(
        conversation_id=conv.id,
        messages=[ChatResponse.model_validate(m) for m in messages],
    )


@router.delete("/history")
def clear_history(
    conversation_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """清空对话消息（conversation_id 不传时清空该用户全部对话消息）"""
    query = db.query(ChatMessageModel).filter(
        ChatMessageModel.user_id == current_user.id
    )
    if conversation_id:
        query = query.filter(ChatMessageModel.conversation_id == conversation_id)
    query.delete()
    db.commit()
    return {"ok": True}
