"""Function-calling schemas for the schedule facade."""

from typing import Any, Dict, List


SCHEDULING_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "preflight_create_calendar_item",
            "description": "Before creating a dated task or subtask, run the user-scoped calendar load preflight. The fourth active item pauses creation and offers three choices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_type": {"type": "string", "enum": ["task", "subtask"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "target_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "parent_task_id": {"type": "integer"},
                    "estimated_hours": {"type": "number", "minimum": 0},
                    "energy_intensity": {"type": "number", "minimum": 0.5, "maximum": 2.0},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                    "hard_deadline_date": {"type": "string"},
                    "earliest_start_date": {"type": "string"},
                    "schedule_kind": {"type": "string"},
                },
                "required": ["source_type", "title", "target_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_overload_intervention",
            "description": "Resolve a pending dated-creation intervention. Choose keep_original, accept_recommendation, or choose_date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "integer"},
                    "decision": {"type": "string", "enum": ["keep_original", "accept_recommendation", "choose_date"]},
                    "selected_date": {"type": "string", "description": "Required for choose_date; YYYY-MM-DD."},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["intervention_id", "decision", "idempotency_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_schedule",
            "description": "Read-only load curve and risk analysis for the authenticated user.",
            "parameters": {"type": "object", "properties": {"start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_schedule_plan",
            "description": "Create a side-effect-free deterministic schedule preview.",
            "parameters": {"type": "object", "properties": {"profile": {"type": "string", "enum": ["conservative", "balanced", "sprint"]}, "idempotency_key": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_schedule_plan",
            "description": "Apply an authenticated owner’s schedule preview atomically after revision validation.",
            "parameters": {"type": "object", "properties": {"plan_id": {"type": "integer"}, "expected_input_revision": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["plan_id", "expected_input_revision", "idempotency_key"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_schedule_plan",
            "description": "Undo an applied schedule plan if no later edit conflicts.",
            "parameters": {"type": "object", "properties": {"plan_id": {"type": "integer"}, "idempotency_key": {"type": "string"}}, "required": ["plan_id", "idempotency_key"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replan_schedule",
            "description": "Recompute a fresh preview from current data and supersede an old preview.",
            "parameters": {"type": "object", "properties": {"plan_id": {"type": "integer"}}, "required": ["plan_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schedule_log",
            "description": "Read sanitized user-scoped scheduling history.",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}, "before_id": {"type": "integer"}}, "required": []},
        },
    },
]
