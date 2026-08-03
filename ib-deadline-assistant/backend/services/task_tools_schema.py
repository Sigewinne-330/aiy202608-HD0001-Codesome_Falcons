"""Function-calling schemas for task and timeline management."""

from typing import Any, Dict, List


TASK_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a task or a process timeline. For IB progress timelines set category and task_type=process.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task or timeline title."},
                    "description": {"type": "string", "description": "Optional scheduling note; do not store academic content."},
                    "subject": {"type": "string", "description": "IA subject, EE subject, TOK track, or CAS record type."},
                    "category": {"type": "string", "enum": ["IA", "EE", "TOK", "CAS"], "description": "IB progress category."},
                    "deadline": {"type": "string", "description": "Final date in YYYY-MM-DD format."},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                    "estimated_hours": {"type": "number", "minimum": 0},
                    "status": {"type": "string", "enum": ["todo", "pending", "in_progress", "done", "overdue"]},
                    "task_type": {"type": "string", "enum": ["todo", "process"]},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List the user's tasks and process timelines. Use this before updating or deleting by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Optional task status filter."},
                    "category": {"type": "string", "enum": ["IA", "EE", "TOK", "CAS"], "description": "Optional IB category filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update an existing task or timeline after locating its task_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "subject": {"type": "string"},
                    "category": {"type": "string", "enum": ["IA", "EE", "TOK", "CAS"]},
                    "deadline": {"type": "string", "description": "YYYY-MM-DD"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                    "estimated_hours": {"type": "number", "minimum": 0},
                    "status": {"type": "string", "enum": ["todo", "pending", "in_progress", "done", "overdue"]},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Delete a task or an entire timeline and all of its milestones. Confirm with the user first.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_subtask",
            "description": "Create a milestone under an existing process timeline. The date is automatically visible in Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "Parent timeline task ID."},
                    "name": {"type": "string", "description": "Milestone name."},
                    "description": {"type": "string", "description": "Optional scheduling note."},
                    "notice_time": {"type": "string", "description": "Milestone deadline in YYYY-MM-DD."},
                    "level": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                },
                "required": ["task_id", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_subtasks",
            "description": "List milestones, optionally for one parent timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_subtask",
            "description": "Update a milestone name, deadline, priority, or completion state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subtask_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "notice_time": {"type": "string", "description": "YYYY-MM-DD"},
                    "level": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                },
                "required": ["subtask_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_subtask",
            "description": "Delete one timeline milestone. Confirm with the user first.",
            "parameters": {
                "type": "object",
                "properties": {"subtask_id": {"type": "integer"}},
                "required": ["subtask_id"],
            },
        },
    },
]
