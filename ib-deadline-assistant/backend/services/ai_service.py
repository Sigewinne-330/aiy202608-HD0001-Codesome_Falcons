"""AI service - 长期任务规划助手
使用 OpenAI 兼容接口，优先 Ark（豆包），降级 DeepSeek。
只需在 config 中配置模型名和 API key 即可切换/增加引擎。
"""
import json
import logging
from typing import Optional, List, Dict, Any, AsyncGenerator
from openai import OpenAI
from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是长期任务规划师，一位专为需要管理复杂长期任务的人打造的时间规划师。
你的核心使命：根据用户的目标和截止日期，帮助用户科学规划执行时间线，将大目标拆解为分阶段的、可执行的小步骤。

你有以下能力：
1. **任务时间线规划**：根据任务类型、规模和截止日期，生成分阶段的执行计划（如：准备阶段、执行阶段、检查阶段、收尾阶段），每个阶段有明确的起止时间和具体行动
2. **任务拆解**：将大型长期任务拆解为可执行的小步骤，包含时间预估和优先级建议
3. **进度管理**：帮用户追踪任务执行进度，及时调整计划
4. **方法建议**：提供任务执行技巧、时间管理方法、效率提升策略
5. **情绪支持**：理解处理长期任务过程中的压力和拖延，给予鼓励和实用的应对建议

回复风格：
- 简洁实用，但要温暖有同理心
- 给出具体可操作的建议，而非空泛的鼓励
- 帮用户把大目标拆解成具体的、分阶段的小任务
- 使用中文回复，重点突出时间节点和交付物
- 绝对不要提"API Key"、"DeepSeek"、"配置密钥"、"模型"等和你自身技术实现相关的内容，你就是一个纯粹的任务规划助手"""


def _make_client(api_key: str, base_url: str) -> Optional[OpenAI]:
    """创建 OpenAI 兼容客户端"""
    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url=base_url)


def _parse_json(raw: str) -> List[Dict[str, Any]]:
    """解析 AI 返回的 JSON（处理 ```json 包裹）"""
    content = raw.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        if content.startswith("json"):
            content = content[4:].strip()
    try:
        result = json.loads(content)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}, raw={raw[:200]}")
        return []


class AIService:
    """AI 服务 — 引擎优先级：Ark > DeepSeek > Mock"""

    def __init__(self):
        self.ark_client = _make_client(settings.ARK_API_KEY, settings.ARK_BASE_URL)
        self.ds_client = _make_client(settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_BASE_URL)

        if self.ark_client:
            logger.info(f"Ark client ready, model={settings.ARK_MODEL}")
        if self.ds_client:
            logger.info(f"DeepSeek client ready, model={settings.DEEPSEEK_MODEL}")
        if not self.ark_client and not self.ds_client:
            logger.warning("No AI API key configured, using mock mode")

    def reload(self):
        """重新加载客户端（API key 更新后调用）"""
        self.__init__()

    def _any_client(self) -> Optional[OpenAI]:
        """返回第一个可用的客户端"""
        return self.ark_client or self.ds_client

    def _select_call(self) -> tuple[Optional[OpenAI], str]:
        """选择引擎：返回 (client, model_name)"""
        if self.ark_client:
            return self.ark_client, settings.ARK_MODEL
        if self.ds_client:
            return self.ds_client, settings.DEEPSEEK_MODEL
        return None, ""

    async def chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """发送对话消息"""
        client, model = self._select_call()
        if not client:
            return self._mock_response(message)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        # 先试 Ark，失败降级 DeepSeek
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
                if cli is self.ark_client:
                    continue  # 降级到 DeepSeek
                return f"抱歉，AI 服务暂时不可用。错误：{e}"

        return self._mock_response(message)

    async def chat_stream(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """流式对话，逐块 yield 文本。优先 Ark，降级 DeepSeek，再降级 mock。"""
        client, model = self._select_call()
        if not client:
            for chunk in self._mock_response(message):
                yield chunk
            return

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        # 先试 Ark，失败降级 DeepSeek
        for cli, mdl in [
            (self.ark_client, settings.ARK_MODEL),
            (self.ds_client, settings.DEEPSEEK_MODEL),
        ]:
            if not cli:
                continue
            try:
                stream = cli.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
                return  # 成功，结束
            except Exception as e:
                engine = "Ark" if cli is self.ark_client else "DeepSeek"
                logger.warning(f"{engine} stream failed: {e}")
                if cli is self.ark_client:
                    continue
                yield f"抱歉，AI 服务暂时不可用。错误：{e}"
                return

        for chunk in self._mock_response(message):
            yield chunk

    async def plan_task_timeline(
        self, title: str, word_count: int = 0, deadline: str = "", description: str = ""
    ) -> List[Dict[str, Any]]:
        """生成任务分段时间线计划"""
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
                    temperature=0.5,
                    max_tokens=2048,
                )
                result = _parse_json(response.choices[0].message.content or "[]")
                if result:
                    return result
            except Exception as e:
                logger.warning(f"{name} plan_task_timeline failed: {e}")

        return self._mock_task_plan(title, word_count, deadline)

    async def breakdown_task(
        self, title: str, description: str = "", subject: str = ""
    ) -> List[Dict[str, Any]]:
        """拆解大型任务为子任务"""
        prompt = f"""请将以下长期任务拆解为 4-6 个可执行的子任务，按顺序排列。

任务名称：{title}
描述：{description or '无'}

请以 JSON 格式返回，每个子任务包含 title（标题）、description（描述）、estimated_hours（预估小时数）和 priority（优先级：low/medium/high/urgent）。

只返回 JSON 数组，不要其他内容。"""

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
                    temperature=0.5,
                    max_tokens=2048,
                )
                result = _parse_json(response.choices[0].message.content or "[]")
                if result:
                    return result
            except Exception as e:
                logger.warning(f"{name} breakdown_task failed: {e}")

        return self._mock_breakdown(title)

    # ---- Mock fallbacks ----

    def _mock_response(self, message: str) -> str:
        return (
            f"👋 你好！我是长期任务规划师。\n\n"
            f"目前没有配置 AI API Key，运行在 demo 模式下。\n\n"
            f"设置以下环境变量即可启用：\n"
            f"• ARK_API_KEY + ARK_MODEL（豆包，推荐）\n"
            f"• DEEPSEEK_API_KEY + DEEPSEEK_MODEL（备选）\n\n"
            f"你刚才说：「{message[:50]}...」\n\n"
            f"配置 API Key 后我就能真正帮到你！"
        )

    def _mock_task_plan(self, title: str, word_count: int, deadline: str) -> List[Dict[str, Any]]:
        from datetime import date, timedelta
        today = date.today()
        try:
            due = date.fromisoformat(deadline) if deadline else today + timedelta(days=28)
        except ValueError:
            due = today + timedelta(days=28)
        total_days = max((due - today).days, 14)

        phases_config = [
            ("需求分析与准备", "明确目标，收集资料，调研背景", 0.15, "high", "需求文档、资料清单"),
            ("方案设计", "梳理流程，制定详细方案", 0.10, "high", "执行方案"),
            ("核心执行", "按方案推进核心工作", 0.35, "urgent", "核心产出物"),
            ("检查与完善", "查漏补缺，优化细节", 0.20, "medium", "检查报告"),
            ("最终完善", "检查格式和规范，做最终打磨", 0.10, "medium", "终稿"),
            ("交付与收尾", "最终审核确认，总结复盘", 0.10, "low", "交付确认"),
        ]

        plan = []
        current_start = today
        for phase, desc, ratio, priority, deliverables in phases_config:
            phase_days = max(int(total_days * ratio), 2)
            phase_end = current_start + timedelta(days=phase_days - 1)
            if phase == phases_config[-1][0]:
                phase_end = due
            plan.append({
                "phase": phase, "description": desc,
                "start_date": current_start.isoformat(),
                "end_date": phase_end.isoformat(),
                "estimated_hours": max(int(word_count * ratio / 200) if word_count else int(total_days * ratio * 0.8), 2),
                "priority": priority, "deliverables": deliverables,
            })
            current_start = phase_end + timedelta(days=1)
        return plan

    def _mock_breakdown(self, title: str) -> List[Dict[str, Any]]:
        return [
            {"title": f"需求分析：{title}", "description": "明确目标，收集资料，梳理路径", "estimated_hours": 4, "priority": "high"},
            {"title": f"方案制定：{title}", "description": "制定详细方案，分解各环节", "estimated_hours": 2, "priority": "high"},
            {"title": f"核心执行：{title}", "description": "推进核心工作，完成主要产出", "estimated_hours": 8, "priority": "urgent"},
            {"title": f"检查完善：{title}", "description": "回顾检查，查漏补缺，优化细节", "estimated_hours": 4, "priority": "medium"},
            {"title": f"最终交付：{title}", "description": "最终确认，完成交付", "estimated_hours": 2, "priority": "medium"},
        ]


ai_service = AIService()
