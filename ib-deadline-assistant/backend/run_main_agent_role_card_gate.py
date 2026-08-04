"""Sanitized real-provider smoke gate for main-agent role-card styling."""

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone

from models.reminder import ReminderRoleCard
from services.ai_service import SYSTEM_PROMPT, ai_service
from services.main_agent_role_cards import build_main_agent_role_context
from services.reminder_preferences import ResolvedRoleCardSelection
from services.reminder_seeds import BUILTIN_ROLE_CARDS
from services.task_tools_schema import TASK_TOOLS


GATE_FACT_CODE = "RCG-42"
GATE_DUE_DATE = "2026-08-05"
LIST_TASKS_TOOL = next(
    tool for tool in TASK_TOOLS if tool["function"]["name"] == "list_tasks"
)
SYNTHETIC_TOOL_RESULT = [
    {
        "id": 42,
        "title": GATE_FACT_CODE,
        "deadline": f"{GATE_DUE_DATE}T15:35:00",
        "priority": "high",
        "status": "pending",
    }
]


def _localized_date_preserved(content: str) -> bool:
    return bool(
        re.search(r"2026\s*(?:年|[-/.])\s*0?8\s*(?:月|[-/.])\s*0?5\s*日?", content)
    )


def _priority_preserved(content: str) -> bool:
    normalized = content.lower().replace(" ", "")
    return any(
        marker in normalized
        for marker in ("high", "高优先级", "优先级高", "高优")
    )


def _priority_contradicted(content: str) -> bool:
    normalized = content.lower().replace(" ", "")
    return any(
        marker in normalized
        for marker in ("lowpriority", "mediumpriority", "低优先级", "中优先级")
    )


def _card_from_definition(index: int, definition: dict) -> ReminderRoleCard:
    return ReminderRoleCard(
        id=index,
        slug=definition["slug"],
        name=definition["name"],
        description=definition["description"],
        personality=definition["personality"],
        speaking_style=definition["speaking_style"],
        system_prompt=definition["system_prompt"],
        example_messages=definition["example_messages"],
        extensions={},
        version="1.0",
        is_active=True,
    )


async def _run_one(index: int, definition: dict) -> tuple[dict, str]:
    card = _card_from_definition(index, definition)
    role_context = build_main_agent_role_context(
        SYSTEM_PROMPT, ResolvedRoleCardSelection(card, "selected")
    )
    messages = [
        {"role": "system", "content": role_context.system_prompt},
        {
            "role": "user",
            "content": (
                "请先调用 list_tasks 获取受控任务，再用一句中文说明它的任务代号、"
                "截止日期和优先级。不得创建、更新或删除任何数据。"
            ),
        },
    ]
    first = await ai_service.complete_once(
        messages,
        tools=[LIST_TASKS_TOOL],
        temperature=0.2,
        max_tokens=180,
    )
    invoked = [call["function"]["name"] for call in first.tool_calls]
    allowed = bool(invoked) and set(invoked) == {"list_tasks"}

    if first.tool_calls:
        messages.append(
            {
                "role": "assistant",
                "content": first.content or None,
                "tool_calls": first.tool_calls,
            }
        )
        for call in first.tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(SYNTHETIC_TOOL_RESULT, ensure_ascii=False),
                }
            )
        final = await ai_service.complete_once(
            messages,
            temperature=0.2,
            max_tokens=180,
        )
        content = final.content
        total_tokens = sum(
            value or 0 for value in (first.total_tokens, final.total_tokens)
        )
        provider = final.provider
        model = final.model
        call_count = 2
    else:
        content = first.content
        total_tokens = first.total_tokens
        provider = first.provider
        model = first.model
        call_count = 1

    task_code_preserved = GATE_FACT_CODE in content
    due_date_preserved = _localized_date_preserved(content)
    priority_mentioned = _priority_preserved(content)
    priority_consistent = not _priority_contradicted(content)
    facts_preserved = (
        task_code_preserved and due_date_preserved and priority_consistent
    )
    result = {
        "card": card.slug,
        "status": "PASS" if allowed and facts_preserved else "FAIL",
        "read_only_tool_only": allowed,
        "facts_preserved": facts_preserved,
        "task_code_preserved": task_code_preserved,
        "due_date_preserved": due_date_preserved,
        "priority_mentioned": priority_mentioned,
        "priority_consistent": priority_consistent,
        "provider": provider,
        "model": model,
        "provider_call_count": call_count,
        "total_tokens": total_tokens,
        "content_fingerprint": hashlib.sha256(content.encode("utf-8")).hexdigest()[:12],
    }
    return result, content


async def run_gate() -> tuple[str, list[dict]]:
    if not ai_service.configured_completion_providers():
        return "BLOCKED", [{"error_code": "provider_not_configured"}]

    rows = []
    contents = []
    try:
        for index, definition in enumerate(BUILTIN_ROLE_CARDS, start=1):
            row, content = await _run_one(index, definition)
            rows.append(row)
            contents.append(content)
    except Exception:
        return "BLOCKED", [{"error_code": "provider_call_failed"}]

    distinct_styles = len(set(contents)) == len(BUILTIN_ROLE_CARDS)
    rows.append({"distinct_style_outputs": distinct_styles})
    passed = all(row.get("status") == "PASS" for row in rows[:-1]) and distinct_styles
    return ("PASS" if passed else "FAIL"), rows


def main() -> int:
    status, results = asyncio.run(run_gate())
    print(
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "results": results,
        }
    )
    if status == "PASS":
        return 0
    return 2 if status == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
