"""OpenAI Function Calling 工具定义 — 注册 6 个 CRUD 工具供 agent 调用

所有操作基于 task 表（主任务）和 sub_task 表（子任务），通过 task_id 外键关联。
"""
from typing import List, Dict, Any

TASK_TOOLS: List[Dict[str, Any]] = [
    # ═══════════════════════ task 表 ═══════════════════════
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": (
                "创建一个新任务。当用户要求'帮我记一下'、'创建一个任务'、'添加待办'、"
                "'新增任务'、'记录一下'时调用此工具。如需修改任务，请先 delete_task 再 create_task。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "任务标题/名称，简洁明确地描述要做什么",
                    },
                    "description": {
                        "type": "string",
                        "description": "任务详细描述、要求、注意事项等",
                    },
                    "deadline": {
                        "type": "string",
                        "description": "截止日期，格式 YYYY-MM-DD，如 2026-08-30",
                    },
                    "status": {
                        "type": "string",
                        "description": "任务状态，如 pending/in_progress/done，默认 pending",
                    },
                    "personal_deadline": {
                        "type": "string",
                        "description": "个人截止时间，格式 YYYY-MM-DD（可早于正式 deadline",
                    },
                    "task_type": {
                        "type": "string",
                        "enum": ["todo", "process"],
                        "description": "任务类型：todo=可直接显示在日历的待办事项；process=流程主任务，会自动创建最终节点，主任务本身不显示在日历",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": (
                "查询用户的所有任务，返回每个任务的完整信息（名称、描述、状态、截止日期等）。"
                "当用户问'我有哪些任务'、'查看所有任务'、'看一下待办列表'、"
                "'还有哪些没完成的'、'列出任务'时调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "按状态过滤：pending/todo=待办, in_progress=进行中, done=已完成, overdue=已逾期。不传返回全部。",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": (
                "删除一个任务及其所有子任务。当用户说'删除任务'、'移除任务'、'取消这个任务'、"
                "'这个不要了'、'删掉XX'时调用此工具。注意：删除不可恢复，请确认后再执行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "要删除的任务 ID。如果用户说的是任务名称，请先调用 list_tasks 找到对应的 ID。",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    # ═══════════════════════ 子任务（sub_task 表） ═══════════════════════
    {
        "type": "function",
        "function": {
            "name": "create_subtask",
            "description": (
                "为指定任务创建一个子任务/子步骤。当用户说'给这个任务加一个子任务'、"
                "'添加步骤'、'拆成小步骤'、'加一个检查点'时调用此工具。"
                "如需修改子任务，请先 delete_subtask 再 create_subtask。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "所属父任务的 ID。如果用户说的是任务名称，请先调用 list_tasks 找到对应的 ID。",
                    },
                    "name": {
                        "type": "string",
                        "description": "子任务名称，简洁明确",
                    },
                    "description": {
                        "type": "string",
                        "description": "子任务的详细描述",
                    },
                    "notice_time": {
                        "type": "string",
                        "description": "子任务截止/提醒日期，格式 YYYY-MM-DD",
                    },
                    "level": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "优先级：low=低, medium=中, high=高, urgent=紧急",
                    },
                    "status": {
                        "type": "string",
                        "description": "状态：pending=待办, in_progress=进行中, done=已完成",
                    },
                },
                "required": ["task_id", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_subtasks",
            "description": (
                "查询子任务列表，返回所有子任务的完整信息。当用户问'有哪些子任务'、"
                "'这个任务的步骤是什么'、'查看子任务'、'看一下检查点'时调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "按父任务 ID 过滤，只返回属于该任务的子任务。不传则返回用户所有子任务。",
                    },
                    "status": {
                        "type": "string",
                        "description": "按状态过滤",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_subtask",
            "description": (
                "删除一个子任务。当用户说'删除这个子任务'、'移除步骤'、'这个步骤不要了'时调用。"
                "注意：删除不可恢复。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subtask_id": {
                        "type": "integer",
                        "description": "要删除的子任务 ID。如果不确定 ID，请先调用 list_subtasks 获取。",
                    },
                },
                "required": ["subtask_id"],
            },
        },
    },
]
