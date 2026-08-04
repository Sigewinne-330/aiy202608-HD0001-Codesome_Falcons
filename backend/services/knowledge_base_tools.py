"""知识库工具 — 读取 knowledge_base/ 目录下的学科指南 .md 文件，供 Agent 调用

架构对齐 task_tools：
  - KNOWLEDGE_BASE_TOOLS  = 工具 schema（OpenAI Function Calling 格式）
  - get_subject_guidelines() = 工具实现（读文件返回 dict）
  - enum 列表从 knowledge_base/ 目录中动态生成，文件名即 subject_task_type
"""
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# 知识库目录（相对于本文件）
_KB_DIR = Path(__file__).parent / "knowledge_base"


def _get_available_subjects() -> List[str]:
    """扫描 knowledge_base/ 目录，返回所有学科名称（.md 文件名去后缀）"""
    if not _KB_DIR.is_dir():
        logger.warning(f"Knowledge base directory not found: {_KB_DIR}")
        return []
    subjects = sorted(
        f.stem for f in _KB_DIR.glob("*.md") if f.is_file()
    )
    logger.info(f"Knowledge base subjects: {subjects}")
    return subjects


def get_subject_guidelines(
    subject_task_type: str,
    **kwargs,
) -> Dict[str, Any]:
    """读取知识库中指定学科的指南文档全文。

    Args:
        subject_task_type: 学科任务类型，如 'IB_Physics_IA'、'AP_History_Essay'
        **kwargs: 兼容 chat.py 的 TOOL_DISPATCH 统一调用约定（忽略额外参数）

    Returns:
        {"ok": True, "subject": str, "content": str}  成功
        {"error": str}                                 文件不存在等
    """
    filepath = _KB_DIR / f"{subject_task_type}.md"

    if not filepath.exists():
        existing = _get_available_subjects()
        msg = (
            f"未找到 '{subject_task_type}' 的指南文件。"
            f"当前可用的学科指南: {existing if existing else '（无）'}"
        )
        logger.warning(msg)
        return {"error": msg}

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read {filepath}: {e}")
        return {"error": f"读取文件失败: {e}"}

    logger.info(
        f"Knowledge base loaded: {subject_task_type}.md ({len(content)} chars)"
    )
    return {
        "ok": True,
        "subject": subject_task_type,
        "content": content,
    }


# ═══════════════════════════════════════════════════════════════
# OpenAI Function Calling 工具定义
# ═══════════════════════════════════════════════════════════════

def build_knowledge_base_tools() -> List[Dict[str, Any]]:
    """构建知识库工具列表。enum 从目录动态生成，新增 .md 文件自动支持。"""
    available = _get_available_subjects()

    return [
        {
            "type": "function",
            "function": {
                "name": "get_subject_guidelines",
                "description": (
                    "当用户要求拆解特定学科的长程任务（如 IB IA、EE、AP 论文、毕业论文等）时，"
                    "必须调用此工具获取该学科的具体拆解指南、评分标准和时间规划建议。"
                    "调用后你会收到一份详细的学科指南文档，请严格遵循其中的步骤、时间分配和建议。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subject_task_type": {
                            "type": "string",
                            "description": (
                                "要查询的学科任务类型。"
                                f"当前可选: {available if available else '暂无'}。"
                                "后续添加新的 .md 文件即可自动支持更多学科。"
                            ),
                            "enum": available,
                        },
                    },
                    "required": ["subject_task_type"],
                },
            },
        },
    ]


# 模块级常量：导入时一次性构建
KNOWLEDGE_BASE_TOOLS: List[Dict[str, Any]] = build_knowledge_base_tools()
