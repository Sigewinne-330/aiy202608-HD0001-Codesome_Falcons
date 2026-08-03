"""AI service - 长期任务规划助手
使用 OpenAI 兼容接口，优先 Ark（豆包），降级 DeepSeek。
只需在 config 中配置模型名和 API key 即可切换/增加引擎。

架构分层：
  模块级工具函数（_make_client, _parse_json）
    → AIService 类
      → 引擎管理层（__init__, reload, _select_call）
      → 对话层（chat, chat_stream）—— 自然语言交互
      → 结构化输出层（plan_task_timeline, breakdown_task）—— 生成数据库可写入的 JSON
      → 失败策略：引擎均不可用时直接抛出 RuntimeError，不再使用 Mock 兜底
"""
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, AsyncGenerator
from openai import OpenAI, AsyncOpenAI
from config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# 模块常量：SYSTEM_PROMPT — 从 system_prompt.md 文件加载
# 每次调用聊天接口时作为 system message 发送
# =============================================================================
_PROMPT_FILE = Path(__file__).parent / "system_prompt.md"
SYSTEM_PROMPT = _PROMPT_FILE.read_text(encoding="utf-8")


# =============================================================================
# 模块级工具：_make_client — OpenAI 兼容客户端工厂
# 职责：用 api_key + base_url 创建统一的客户端实例，key 为空时返回 None
# 被调用：AIService.__init__()
# =============================================================================
def _make_client(api_key: str, base_url: str) -> Optional[OpenAI]:
    """创建同步 OpenAI 兼容客户端（用于 chat、工具调用、结构化输出）"""
    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url=base_url)


def _make_async_client(api_key: str, base_url: str) -> Optional[AsyncOpenAI]:
    """创建异步 OpenAI 兼容客户端（用于流式对话）"""
    if not api_key:
        return None
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


# =============================================================================
# 模块级工具：_parse_json — 防御式 JSON 清洗解析器
# 职责：清洗 AI 返回的原始文本（去除 ```json 包裹、语言标识），解析为列表
# 被调用：plan_task_timeline(), breakdown_task()
# 核心逻辑：
#   1. 检测并剥离 markdown 代码块标记（``` ... ```）
#   2. 去除 "json" 语言前缀
#   3. json.loads() 解析，非列表或解析失败统一返回 []
# =============================================================================
def _parse_json(raw: str) -> List[Dict[str, Any]]:
    """解析 AI 返回的 JSON（处理 ```json 包裹）"""
    content = raw.strip()
    # 清洗：剥离 markdown 代码块 ` ```json ... ``` `
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        if content.startswith("json"):
            content = content[4:].strip()
    # 解析：JSONDecodeError 不抛异常，返回空列表保证调用链不中断
    try:
        result = json.loads(content)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}, raw={raw[:200]}")
        return []


# =============================================================================
# AIService — AI 服务主类
# =============================================================================
# 整体职责：封装对多个 AI 引擎的调用，提供对话、流式对话、结构化输出三种
#         接口，内置优先级链（Ark → DeepSeek）和自动降级机制，均失败则直接报错
# =============================================================================
class AIService:
    """AI 服务 — 引擎优先级：Ark > DeepSeek，均失败则直接报错"""

    # =========================================================================
    # 引擎管理层：负责多个 AI 客户端的初始化、选择和热重载
    # 方法：__init__, reload, _any_client, _select_call
    # =========================================================================

    def __init__(self):
        """初始化：按配置创建 Ark 和 DeepSeek 两个客户端，任一未配 key 则为 None"""
        self.ark_client = _make_client(settings.ARK_API_KEY, settings.ARK_BASE_URL)
        self.ds_client = _make_client(settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_BASE_URL)
        self.ark_async = _make_async_client(settings.ARK_API_KEY, settings.ARK_BASE_URL)
        self.ds_async = _make_async_client(settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_BASE_URL)

        # 日志：告知运维当前哪些引擎可用
        if self.ark_client:
            logger.info(f"Ark client ready, model={settings.ARK_MODEL}")
        if self.ds_client:
            logger.info(f"DeepSeek client ready, model={settings.DEEPSEEK_MODEL}")
        if not self.ark_client and not self.ds_client:
            logger.error("No AI API key configured, all AI calls will fail")

    def reload(self):
        """重新加载客户端（API key 更新后调用）"""
        self.__init__()

    def _any_client(self) -> Optional[OpenAI]:
        """返回第一个可用的客户端（用于简单探测）"""
        return self.ark_client or self.ds_client

    def _select_call(self) -> tuple[Optional[OpenAI], str]:
        """选择引擎：按优先级 Ark → DeepSeek 返回 (client, model_name)
        返回值两个都用 Optional：以便调用方统一判断无引擎可用的降级路径
        """
        if self.ark_client:
            return self.ark_client, settings.ARK_MODEL
        if self.ds_client:
            return self.ds_client, settings.DEEPSEEK_MODEL
        return None, ""

    # =========================================================================
    # 对话层：提供同步和流式两种自然语言对话能力
    # 职责：构建 messages（system + history + user），调 AI，降级兜底
    # 调用方：routers/chat.py 的 /api/chat 端点
    # =========================================================================

    async def chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """同步对话：一次性返回完整回复。适用场景：非实时交互、后端批量处理"""
        client, model = self._select_call()
        if not client:
            raise RuntimeError("所有 AI 引擎均未配置 API Key，无法完成对话。请检查 ARK_API_KEY 或 DEEPSEEK_API_KEY 配置。")

        # 构建消息：system prompt(角色) + 历史对话 + 当前用户消息
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        # 降级链路：Ark 失败 → DeepSeek，均失败则抛出异常
        last_error = None
        for attempt, (cli, mdl) in enumerate([
            (self.ark_client, settings.ARK_MODEL),
            (self.ds_client, settings.DEEPSEEK_MODEL),
        ]):
            if not cli:
                continue
            try:
                response = cli.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                engine = "Ark" if cli is self.ark_client else "DeepSeek"
                logger.warning(f"{engine} chat failed: {e}")
                last_error = e
                if cli is self.ark_client:
                    continue  # 降级到 DeepSeek

        raise RuntimeError(f"所有 AI 引擎调用均失败，无法完成对话。最后错误：{last_error}")

    async def chat_stream(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """流式对话，逐块 yield 文本。使用 AsyncOpenAI 非阻塞迭代。"""
        # 没有任何客户端 → 直接报错
        if not self.ark_async and not self.ds_async:
            yield "抱歉，所有 AI 引擎均未配置 API Key，无法完成流式对话。"
            return

        # 构建消息：与 chat() 一致
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        # 降级链路同 chat()，区别在于用 stream=True 逐块产出
        for cli, mdl in [
            (self.ark_async, settings.ARK_MODEL),
            (self.ds_async, settings.DEEPSEEK_MODEL),
        ]:
            if not cli:
                continue
            try:
                kwargs = {}
                # 关闭深度思考模式（仅 Ark 支持该参数），加速首字返回
                if cli is self.ark_async:
                    kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                stream = await cli.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                    stream=True,
                    **kwargs,
                )
                engine = "Ark" if cli is self.ark_async else "DeepSeek"
                logger.info(f"[LLM-STREAM] engine={engine}, model={mdl} 开始流式返回")
                full_content = []
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        full_content.append(delta.content)
                        logger.info(f"[LLM-CHUNK] {delta.content!r}")
                        yield delta.content  # 保持流式逐块返回
                logger.info(f"[LLM-DONE] 完整返回（{len(''.join(full_content))} 字符）:\n{''.join(full_content)}")
                return  # 成功，结束
            except Exception as e:
                engine = "Ark" if cli is self.ark_async else "DeepSeek"
                logger.warning(f"{engine} stream failed: {e}")
                if cli is self.ark_async:
                    continue

        # 所有引擎失败：直接报错
        yield "抱歉，所有 AI 引擎调用均失败，无法完成流式对话。"

    async def chat_stream_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式对话 + 工具调用。逐 chunk 推送文本，流结束时若有 tool_calls 则集中 yield。

        产出事件格式：
          {"type": "text", "content": "..."}       — 普通文本 delta，可直接推前端
          {"type": "tool_calls", "tool_calls": [...]} — 模型决定调工具，返回完整调用列表

        调用方拿到 tool_calls 事件后应执行工具、喂回结果、重新调用本方法。

        引擎：Ark → DeepSeek（均用 AsyncOpenAI）
        """
        if not self.ark_async and not self.ds_async:
            raise RuntimeError("所有 AI 引擎均未配置 API Key，无法完成流式工具调用。")

        last_error = None
        for cli, mdl in [
            (self.ark_async, settings.ARK_MODEL),
            (self.ds_async, settings.DEEPSEEK_MODEL),
        ]:
            if not cli:
                continue
            try:
                kwargs = {
                    "model": mdl,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": 0.7,
                    "max_tokens": 2048,
                    "stream": True,
                }
                # Ark 关闭深度思考，加速首字
                if cli is self.ark_async:
                    kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

                engine = "Ark" if cli is self.ark_async else "DeepSeek"
                logger.info(f"[LLM-STREAM-TOOLS] engine={engine}, model={mdl}")

                stream = await cli.chat.completions.create(**kwargs)

                # 累积工具调用的 delta 分片
                tool_calls_acc: List[Dict[str, Any]] = []
                full_text: List[str] = []

                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    # 普通文本 → 即时推送 + 终端日志
                    if delta.content:
                        full_text.append(delta.content)
                        logger.info(f"[LLM-CHUNK] {delta.content!r}")
                        yield {"type": "text", "content": delta.content}

                    # 工具调用 delta → 累积不推送 + 终端日志
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            while len(tool_calls_acc) <= tc.index:
                                tool_calls_acc.append({
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                })
                            acc = tool_calls_acc[tc.index]
                            if tc.id:
                                acc["id"] = tc.id
                            if tc.function and tc.function.name:
                                logger.info(f"[LLM-TOOL] name={tc.function.name!r}")
                                acc["function"]["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                logger.info(f"[LLM-TOOL-ARG] {tc.function.arguments!r}")
                                acc["function"]["arguments"] += tc.function.arguments

                # 流结束：日志汇总
                final_text = "".join(full_text)
                if tool_calls_acc:
                    logger.info(f"[LLM-TOOLS] tool_calls={[t['function']['name'] for t in tool_calls_acc]} text={final_text[:80]!r}")
                    yield {"type": "tool_calls", "tool_calls": tool_calls_acc}
                else:
                    logger.info(f"[LLM-DONE] 完整返回（{len(final_text)} 字符）:\n{final_text}")

                return  # 成功

            except Exception as e:
                engine = "Ark" if cli is self.ark_async else "DeepSeek"
                logger.warning(f"{engine} chat_stream_with_tools failed: {e}")
                last_error = e
                if cli is self.ark_async:
                    continue

        raise RuntimeError(f"所有 AI 引擎流式工具调用均失败。最后错误：{last_error}")

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """带工具调用的对话：发送 messages + tools，返回原始 choice 对象。

        与 chat() 的区别：
        - 不构建 messages（调用方已构建好 system + history + user）
        - 支持 tools 参数（OpenAI function calling）
        - 直接返回 choices[0]，调用方可检查 tool_calls

        调用方：routers/chat.py 的工具调用循环
        """
        client, model = self._select_call()
        if not client:
            raise RuntimeError("所有 AI 引擎均未配置 API Key，无法完成工具调用。")

        last_error = None
        for cli, mdl in [
            (self.ark_client, settings.ARK_MODEL),
            (self.ds_client, settings.DEEPSEEK_MODEL),
        ]:
            if not cli:
                continue
            try:
                kwargs = {
                    "model": mdl,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 2048,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                response = cli.chat.completions.create(**kwargs)
                return response.choices[0]
            except Exception as e:
                engine = "Ark" if cli is self.ark_client else "DeepSeek"
                logger.warning(f"{engine} chat_with_tools failed: {e}")
                last_error = e
                if cli is self.ark_client:
                    continue

        raise RuntimeError(f"所有 AI 引擎工具调用均失败。最后错误：{last_error}")

    # =========================================================================
    # 结构化输出层：要求 AI 返回结构化 JSON，解析后写入数据库
    # 职责：构建 JSON schema prompt → 调 AI(temperature=0.5) → _parse_json() 清洗
    # 调用方：routers/tasks.py 的 POST /api/tasks/plan 和 /api/tasks/breakdown
    # 特点：temperature 降为 0.5 提高格式稳定性；空结果也会触发引擎降级
    # =========================================================================

    async def plan_task_timeline(
        self, title: str, word_count: int = 0, deadline: str = "", description: str = ""
    ) -> List[Dict[str, Any]]:
        """时间线规划：根据截止日期倒推，生成 4-6 个阶段，每阶段含起止日期和交付物
        被调用：POST /api/tasks/plan — 用户创建新任务时触发
        返回结构：[{phase, description, start_date, end_date, estimated_hours, priority, deliverables}]"""

        # 构建结构化 prompt：定义 JSON schema，要求只返回数组
        prompt = f"""请为以下长期任务生成一个分阶段的时间线计划。

任务名称：{title}
任务规模：{word_count}（可以是字数、工作量或其他量化指标）
截止日期：{deadline}
补充说明：{description or '无'}

请根据截止日期倒推，将任务拆解为 4-6 个阶段，每个阶段分配合理的起止时间。
请以 JSON 格式返回，每个阶段包含：
- phase（阶段名称）
- description（该阶段的具体行动描述）
- start_date（开始日期，格式 YYYY-MM-DD）
- end_date（结束日期，格式 YYYY-MM-DD）
- estimated_hours（预估耗时，数字）
- priority（优先级：low/medium/high/urgent）
- deliverables（该阶段的交付物）

只返回 JSON 数组，不要其他内容。"""

        # 降级重试：空结果也会触发引擎切换（因为 AI 可能返回了格式不合规的内容）
        for cli, mdl, name in [
            (self.ark_client, settings.ARK_MODEL, "Ark"),
            (self.ds_client, settings.DEEPSEEK_MODEL, "DeepSeek"),
        ]:
            if not cli:
                continue
            try:
                response = cli.chat.completions.create(
                    model=mdl,
                    messages=[
                        {"role": "system", "content": "你是一个任务规划专家，只返回 JSON 数组。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.5,   # 低于聊天(0.7)，提高 JSON 格式稳定性
                    max_tokens=2048,
                )
                result = _parse_json(response.choices[0].message.content or "[]")
                if result:
                    return result
                # 解析为空 → 继续尝试下一个引擎
            except Exception as e:
                logger.warning(f"{name} plan_task_timeline failed: {e}")

        # 所有引擎失败：直接抛出异常
        raise RuntimeError("所有 AI 引擎均无法完成任务时间线规划。请检查 API Key 配置或网络连接。")

    async def breakdown_task(
        self, title: str, description: str = "", subject: str = ""
    ) -> List[Dict[str, Any]]:
        """任务拆解：将一个大任务拆分为 4-6 个可执行的子任务
        被调用：POST /api/tasks/breakdown — 用户对已有任务点击"AI 拆解"
        返回结构：[{title, description, estimated_hours, priority}]"""

        # 构建结构化 prompt：与 plan_task_timeline 不同，不涉及时间维度
        prompt = f"""请将以下长期任务拆解为 4-6 个可执行的子任务，按顺序排列。

任务名称：{title}
描述：{description or '无'}

请以 JSON 格式返回，每个子任务包含 title（标题）、description（描述）、estimated_hours（预估小时数）和 priority（优先级：low/medium/high/urgent）。

只返回 JSON 数组，不要其他内容。"""

        # 降级重试：骨架与 plan_task_timeline() 完全一致
        for cli, mdl, name in [
            (self.ark_client, settings.ARK_MODEL, "Ark"),
            (self.ds_client, settings.DEEPSEEK_MODEL, "DeepSeek"),
        ]:
            if not cli:
                continue
            try:
                response = cli.chat.completions.create(
                    model=mdl,
                    messages=[
                        {"role": "system", "content": "你是一个任务规划专家，只返回 JSON 数组。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.5,   # 低于聊天(0.7)，提高 JSON 格式稳定性
                    max_tokens=2048,
                )
                result = _parse_json(response.choices[0].message.content or "[]")
                if result:
                    return result
                # 解析为空 → 继续尝试下一个引擎
            except Exception as e:
                logger.warning(f"{name} breakdown_task failed: {e}")

        # 所有引擎失败：直接抛出异常
        raise RuntimeError("所有 AI 引擎均无法完成任务拆解。请检查 API Key 配置或网络连接。")

    # =========================================================================
    # [已废弃] Mock 降级层：原先用于无 API key 时的离线兜底
    # 当前策略：所有引擎均失败时直接抛出 RuntimeError，不再使用 Mock
    # =========================================================================

    # def _mock_response(self, message: str) -> str:
    #     """Mock 对话回复：告知用户当前为 demo 模式，指导如何配置 API key"""
    #     return (
    #         f"👋 你好！我是长期任务规划师。\n\n"
    #         f"目前没有配置 AI API Key，运行在 demo 模式下。\n\n"
    #         f"设置以下环境变量即可启用：\n"
    #         f"• ARK_API_KEY + ARK_MODEL（豆包，推荐）\n"
    #         f"• DEEPSEEK_API_KEY + DEEPSEEK_MODEL（备选）\n\n"
    #         f"你刚才说：「{message[:50]}...」\n\n"
    #         f"配置 API Key 后我就能真正帮到你！"
    #     )

    # def _mock_task_plan(self, title: str, word_count: int, deadline: str) -> List[Dict[str, Any]]:
    #     """Mock 时间线规划：用纯算法按比例分配阶段"""
    #     from datetime import date, timedelta
    #     today = date.today()
    #     try:
    #         due = date.fromisoformat(deadline) if deadline else today + timedelta(days=28)
    #     except ValueError:
    #         due = today + timedelta(days=28)
    #     total_days = max((due - today).days, 14)
    #
    #     phases_config = [
    #         ("需求分析与准备", "明确目标，收集资料，调研背景", 0.15, "high", "需求文档、资料清单"),
    #         ("方案设计", "梳理流程，制定详细方案", 0.10, "high", "执行方案"),
    #         ("核心执行", "按方案推进核心工作", 0.35, "urgent", "核心产出物"),
    #         ("检查与完善", "查漏补缺，优化细节", 0.20, "medium", "检查报告"),
    #         ("最终完善", "检查格式和规范，做最终打磨", 0.10, "medium", "终稿"),
    #         ("交付与收尾", "最终审核确认，总结复盘", 0.10, "low", "交付确认"),
    #     ]
    #
    #     plan = []
    #     current_start = today
    #     for phase, desc, ratio, priority, deliverables in phases_config:
    #         phase_days = max(int(total_days * ratio), 2)
    #         phase_end = current_start + timedelta(days=phase_days - 1)
    #         if phase == phases_config[-1][0]:
    #             phase_end = due
    #         plan.append({
    #             "phase": phase, "description": desc,
    #             "start_date": current_start.isoformat(),
    #             "end_date": phase_end.isoformat(),
    #             "estimated_hours": max(int(word_count * ratio / 200) if word_count else int(total_days * ratio * 0.8), 2),
    #             "priority": priority, "deliverables": deliverables,
    #         })
    #         current_start = phase_end + timedelta(days=1)
    #     return plan

    # def _mock_breakdown(self, title: str) -> List[Dict[str, Any]]:
    #     """Mock 任务拆解：返回固定的 5 阶段模板子任务列表"""
    #     return [
    #         {"title": f"需求分析：{title}", "description": "明确目标，收集资料，梳理路径", "estimated_hours": 4, "priority": "high"},
    #         {"title": f"方案制定：{title}", "description": "制定详细方案，分解各环节", "estimated_hours": 2, "priority": "high"},
    #         {"title": f"核心执行：{title}", "description": "推进核心工作，完成主要产出", "estimated_hours": 8, "priority": "urgent"},
    #         {"title": f"检查完善：{title}", "description": "回顾检查，查漏补缺，优化细节", "estimated_hours": 4, "priority": "medium"},
    #         {"title": f"最终交付：{title}", "description": "最终确认，完成交付", "estimated_hours": 2, "priority": "medium"},
    #     ]


# =============================================================================
# 模块级单例：全局共享的 AI 服务实例
# 被所有路由模块通过 `from services.ai_service import ai_service` 引用
# =============================================================================
ai_service = AIService()
