import asyncio
import hashlib
from datetime import date, datetime, timezone
from uuid import uuid4

import models  # noqa: F401 - register metadata
from database import SessionLocal
from models.reminder import (
    LLMUsageRecord,
    ReminderDigest,
    ReminderGenerationMode,
    ReminderRoleCard,
)
from models.user import User
from services.ai_service import SYSTEM_PROMPT, ai_service
from services.reminder_agent import REMINDER_SYSTEM_PROMPT, ReminderTextAgent
from services.reminder_seeds import BUILTIN_ROLE_CARDS, seed_builtin_role_cards


class TrackingCompletionService:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def configured_completion_providers(self):
        return self.inner.configured_completion_providers()

    async def complete_once(self, messages, **kwargs):
        result = await self.inner.complete_once(messages, **kwargs)
        self.calls.append(
            {
                "dedicated_prompt": (
                    messages[0]["content"] == REMINDER_SYSTEM_PROMPT
                    and messages[0]["content"] != SYSTEM_PROMPT
                ),
                "allowed_tools": sorted(
                    tool["function"]["name"] for tool in kwargs.get("tools", [])
                ),
                "invoked_tools": sorted(
                    call["function"]["name"] for call in result.tool_calls
                ),
                "provider": result.provider,
                "model": result.model,
            }
        )
        return result


class DisabledCompletionService:
    def configured_completion_providers(self):
        return []


async def run_gate() -> list[dict]:
    suffix = uuid4().hex[:12]
    username = f"reminder_llm_gate_{suffix}"
    user_id = None
    results = []
    tracker = TrackingCompletionService(ai_service)
    try:
        with SessionLocal() as db:
            seed_builtin_role_cards(db)
            user = User(
                username=username,
                email=f"{username}@example.com",
                password="provider-gate-only",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            user_id = user.id

            cards = {
                card.slug: card
                for card in db.query(ReminderRoleCard)
                .filter(
                    ReminderRoleCard.slug.in_(
                        [definition["slug"] for definition in BUILTIN_ROLE_CARDS]
                    )
                )
                .all()
            }
            snapshots = [
                {
                    "item_type": "task",
                    "item_id": 100,
                    "title": "受控验收任务",
                    "description": "用于验证提醒生成边界的合成数据。",
                    "due_date": "2026-08-05",
                    "cadence_offset": 2,
                    "cadence_label": "D-2",
                    "priority": "high",
                    "subject": "Provider gate",
                    "progress": 20,
                }
            ]

            for index, definition in enumerate(BUILTIN_ROLE_CARDS):
                card = cards[definition["slug"]]
                digest = ReminderDigest(
                    user_id=user.id,
                    local_date=date(2026, 8, 3 + index),
                    timezone="Asia/Shanghai",
                    language="zh-CN",
                    role_card_id=card.id,
                    item_snapshot=snapshots,
                )
                db.add(digest)
                db.commit()
                db.refresh(digest)
                first_call = len(tracker.calls)
                generated = await ReminderTextAgent(tracker).generate(
                    db,
                    user_id=user.id,
                    digest_id=digest.id,
                    language="zh-CN",
                    role_card=card,
                    item_snapshots=snapshots,
                    app_base_url="https://assistant.example.test",
                )
                calls = tracker.calls[first_call:]
                usage = (
                    db.query(LLMUsageRecord)
                    .filter(LLMUsageRecord.reminder_digest_id == digest.id)
                    .all()
                )
                has_cjk = any("\u4e00" <= char <= "\u9fff" for char in generated.framing)
                results.append(
                    {
                        "card": card.slug,
                        "mode": generated.mode.value,
                        "attempts": generated.attempts,
                        "contract": (
                            generated.mode == ReminderGenerationMode.llm
                            and has_cjk
                            and generated.body.endswith("/chat")
                        ),
                        "dedicated_prompt": bool(calls)
                        and all(call["dedicated_prompt"] for call in calls),
                        "allowed_tools": sorted(
                            {name for call in calls for name in call["allowed_tools"]}
                        ),
                        "invoked_tools": sorted(
                            {name for call in calls for name in call["invoked_tools"]}
                        ),
                        "usage_records": len(usage),
                        "usage_accounted": bool(usage)
                        and all(row.total_tokens is not None for row in usage),
                        "provider": calls[-1]["provider"] if calls else None,
                        "model": calls[-1]["model"] if calls else None,
                        "content_fingerprint": hashlib.sha256(
                            (generated.subject + "\n" + generated.framing).encode("utf-8")
                        ).hexdigest()[:12],
                    }
                )

            fallback_digest = ReminderDigest(
                user_id=user.id,
                local_date=date(2026, 8, 10),
                timezone="Asia/Shanghai",
                language="zh-CN",
                role_card_id=cards["friendly-warm-guy"].id,
                item_snapshot=snapshots,
            )
            db.add(fallback_digest)
            db.commit()
            fallback = await ReminderTextAgent(DisabledCompletionService()).generate(
                db,
                user_id=user.id,
                digest_id=fallback_digest.id,
                language="zh-CN",
                role_card=cards["friendly-warm-guy"],
                item_snapshots=snapshots,
                app_base_url="https://assistant.example.test",
            )
            results.append(
                {
                    "fallback": fallback.mode == ReminderGenerationMode.template,
                    "attempts": fallback.attempts,
                }
            )
    finally:
        if user_id is not None:
            with SessionLocal() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    db.delete(user)
                    db.commit()
    return results


def main() -> int:
    results = asyncio.run(run_gate())
    expected_tools = ["list_deadlines", "list_subtasks", "list_tasks"]
    card_results = [row for row in results if "card" in row]
    passed = (
        len(card_results) == 3
        and len({row["content_fingerprint"] for row in card_results}) == 3
        and all(
            row["contract"]
            and row["dedicated_prompt"]
            and row["allowed_tools"] == expected_tools
            and row["usage_accounted"]
            for row in card_results
        )
        and results[-1] == {"fallback": True, "attempts": 0}
    )
    print(
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if passed else "FAIL",
            "cards": card_results,
            "deterministic_fallback": results[-1],
        }
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
