"""DeepSeek AI service - 长期任务规划助手"""
import json
import logging
from typing import Optional, List, Dict, Any
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
- 使用中文回复，重点突出时间节点和交付物"""


class AIService:
    """AI 对话服务"""

    def __init__(self):
        self.client: Optional[OpenAI] = None
        self._init_client()

    def _init_client(self):
        if settings.DEEPSEEK_API_KEY:
            self.client = OpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
            )
            logger.info("DeepSeek client initialized")
        else:
            logger.warning("DEEPSEEK_API_KEY not set, using mock responses")

    def reload(self):
        """重新加载客户端（API key 更新后调用）"""
        self._init_client()

    async def chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """发送对话消息，返回 AI 回复"""
        if not self.client:
            return self._mock_response(message)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        try:
            response = self.client.chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}")
            return f"抱歉，AI 服务暂时不可用，请稍后重试。错误信息：{str(e)}"

    async def plan_task_timeline(
        self, title: str, word_count: int = 0, deadline: str = "", description: str = ""
    ) -> List[Dict[str, Any]]:
        """用 AI 生成任务分段时间线计划"""
        prompt = f"""请为以下长期任务生成一个分阶段的时间线计划。

任务名称：{title}
任务规模：{word_count}（可以是字数、工作量或其他量化指标）
截止日期：{deadline}
补充说明：{description or '无'}

请根据截止日期倒推，将任务拆解为 4-6 个阶段，每个阶段分配合理的起止时间。
请以 JSON 格式返回，每个阶段包含：
- phase（阶段名称，如"需求分析与准备"、"方案设计"、"核心执行"、"检查与测试"、"收尾完善"、"最终交付"）
- description（该阶段的具体行动描述）
- start_date（开始日期，格式 YYYY-MM-DD）
- end_date（结束日期，格式 YYYY-MM-DD）
- estimated_hours（预估耗时，数字）
- priority（优先级：low/medium/high/urgent）
- deliverables（该阶段的交付物，如"需求文档"、"设计方案"等）

只返回 JSON 数组，不要其他内容。"""

        if not self.client:
            return self._mock_task_plan(title, word_count, deadline)

        try:
            response = self.client.chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个任务规划专家，擅长根据截止日期倒推生成分阶段的执行计划。只返回 JSON，不要其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=2048,
            )
            content = response.choices[0].message.content or "[]"
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                if content.startswith("json"):
                    content = content[4:].strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Task plan error: {e}")
            return self._mock_task_plan(title, word_count, deadline)

    async def breakdown_task(
        self, title: str, description: str = "", subject: str = ""
    ) -> List[Dict[str, Any]]:
        """用 AI 拆解大型任务为子任务"""
        prompt = f"""请将以下长期任务拆解为 4-6 个可执行的子任务，按顺序排列。

任务名称：{title}
描述：{description or '无'}

请以 JSON 格式返回，每个子任务包含 title（标题）、description（描述）、estimated_hours（预估小时数）和 priority（优先级：low/medium/high/urgent）。

只返回 JSON 数组，不要其他内容。"""

        if not self.client:
            return self._mock_breakdown(title)

        try:
            response = self.client.chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个任务规划专家，擅长将大型任务拆解为可执行的子任务。只返回 JSON，不要其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=2048,
            )
            content = response.choices[0].message.content or "[]"
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                if content.startswith("json"):
                    content = content[4:].strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Task breakdown error: {e}")
            return self._mock_breakdown(title)

    def _mock_response(self, message: str) -> str:
        """Mock 回复（无 API key 时使用）"""
        return (
            f"👋 你好！我是长期任务规划师。\n\n"
            f"我注意到你还没有配置 DeepSeek API Key，所以目前我运行在 demo 模式下。\n\n"
            f"一旦配置了 API Key，我就可以：\n"
            f"• 根据截止日期帮你规划任务执行时间线\n"
            f"• 将大型任务拆解为分阶段的可执行步骤\n"
            f"• 追踪执行进度并给出调整建议\n"
            f"• 提供任务管理技巧和时间管理方法\n\n"
            f"你刚才说：「{message[:50]}...」\n\n"
            f"请先配置 DeepSeek API Key，让我真正帮到你！"
        )

    def _mock_task_plan(self, title: str, word_count: int, deadline: str) -> List[Dict[str, Any]]:
        """Mock 任务规划（无 API key 时使用）- 生成分段时间线"""
        from datetime import date, timedelta
        today = date.today()

        # 根据截止日期和今天计算总天数
        try:
            due = date.fromisoformat(deadline) if deadline else today + timedelta(days=28)
        except ValueError:
            due = today + timedelta(days=28)

        total_days = max((due - today).days, 14)

        # 按比例分配各阶段天数（通用任务阶段模板）
        phases_config = [
            ("需求分析与准备", "明确目标，收集资料，调研背景，确定执行方向和关键路径", 0.15, "high", "需求文档、资料清单"),
            ("方案设计", "梳理执行流程，制定详细方案，明确各环节安排和资源需求", 0.10, "high", "执行方案"),
            ("核心执行", "按方案推进核心工作，完成关键内容，持续推进进度", 0.35, "urgent", "核心产出物"),
            ("检查与完善", "回顾已完成部分，查漏补缺，优化细节，调整不合理之处", 0.20, "medium", "修改稿/检查报告"),
            ("最终完善", "检查格式、规范和质量，优化表达，做最终打磨", 0.10, "medium", "终稿/最终产出"),
            ("交付与收尾", "进行最终审核确认，完成提交或交付，总结经验", 0.10, "low", "交付确认"),
        ]

        plan = []
        current_start = today
        for phase, desc, ratio, priority, deliverables in phases_config:
            phase_days = max(int(total_days * ratio), 2)
            phase_end = current_start + timedelta(days=phase_days - 1)
            # 最后一个阶段结束于截止日期
            if phase == phases_config[-1][0]:
                phase_end = due

            plan.append({
                "phase": phase,
                "description": desc,
                "start_date": current_start.isoformat(),
                "end_date": phase_end.isoformat(),
                "estimated_hours": max(int(word_count * ratio / 200) if word_count else int(total_days * ratio * 0.8), 2),
                "priority": priority,
                "deliverables": deliverables,
            })
            current_start = phase_end + timedelta(days=1)

        return plan

    def _mock_breakdown(self, title: str) -> List[Dict[str, Any]]:
        return [
            {"title": f"需求分析：{title}", "description": "明确目标要求，收集相关资料，梳理执行路径", "estimated_hours": 4, "priority": "high"},
            {"title": f"方案制定：{title}", "description": "制定详细执行方案，分解各环节任务", "estimated_hours": 2, "priority": "high"},
            {"title": f"核心执行：{title}", "description": "按方案推进核心工作，完成主要产出", "estimated_hours": 8, "priority": "urgent"},
            {"title": f"检查完善：{title}", "description": "回顾检查已完成部分，查漏补缺，优化细节", "estimated_hours": 4, "priority": "medium"},
            {"title": f"最终交付：{title}", "description": "最终检查确认，完成交付或提交", "estimated_hours": 2, "priority": "medium"},
        ]


# 全局单例
ai_service = AIService()
