"""Optional effort-estimation boundary for the scheduler.

The deterministic engine never calls this module.  An Agent or future API may
explicitly request an estimate; provider usage is recorded through the same
ledger used by the existing AI service and a bounded deterministic fallback is
returned on every failure.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from services.ai_service import ai_service
from services.llm_usage import LLMQuotaPolicy, record_llm_usage


SCHEDULE_ESTIMATION_SYSTEM_PROMPT = (
    "You are a scheduling effort estimator. Return JSON only: "
    "{\"estimated_hours\": number, \"confidence\": number}. "
    "Use a coarse estimate from 0.5 to 24 hours. Never make a date, policy, "
    "permission, or calendar mutation decision."
)
SCHEDULE_EXPLANATION_SYSTEM_PROMPT = (
    "You are a text-only scheduling explanation agent. Write one or two short "
    "sentences in the requested language using only the supplied structured "
    "facts. Do not change, reorder, or invent dates, effort, scores, reasons, "
    "permissions, or decisions. Return plain text only."
)


@dataclass(frozen=True)
class EffortEstimate:
    estimated_hours: float
    confidence: float
    source: str
    provider: Optional[str] = None
    model: Optional[str] = None
    total_tokens: Optional[int] = None
    correlation_id: str = ""


@dataclass(frozen=True)
class ScheduleExplanation:
    text: str
    source: str
    provider: Optional[str] = None
    model: Optional[str] = None
    total_tokens: Optional[int] = None
    correlation_id: str = ""


def _fallback(correlation_id: str) -> EffortEstimate:
    return EffortEstimate(
        estimated_hours=1.0,
        confidence=0.0,
        source="default",
        correlation_id=correlation_id,
    )


def _parse(content: str) -> tuple[float, float]:
    match = re.search(r"\{.*\}", content or "", flags=re.DOTALL)
    if not match:
        raise ValueError("estimate is not JSON")
    payload = json.loads(match.group(0))
    hours = min(24.0, max(0.5, float(payload["estimated_hours"])))
    confidence = min(1.0, max(0.0, float(payload.get("confidence", 0.5))))
    return hours, confidence


def deterministic_explanation(recommendation: dict, language: str = "zh-CN") -> str:
    target = str(recommendation.get("date") or "")[:10]
    effort = max(0.0, min(24.0, float(recommendation.get("recommended_effort_hours") or 0)))
    ratio = max(0.0, float(recommendation.get("energy_ratio") or 0))
    increase = bool(recommendation.get("increase_effort"))
    if str(language).lower().startswith("zh"):
        pace = "建议适当增加当天投入" if increase else "不建议额外加量"
        return f"建议安排在 {target}，计划投入约 {effort:g} 小时，预计负载为 {ratio:.0%}；{pace}。"
    pace = "A modest increase in effort is recommended" if increase else "No extra effort is recommended"
    return f"Schedule it for {target} with about {effort:g} hours at {ratio:.0%} projected load. {pace} for that day."


def _structured_explanation_payload(recommendation: dict) -> dict:
    return {
        "date": str(recommendation.get("date") or "")[:10],
        "recommended_effort_hours": max(
            0.0,
            min(24.0, float(recommendation.get("recommended_effort_hours") or 0)),
        ),
        "energy_ratio": max(0.0, min(10.0, float(recommendation.get("energy_ratio") or 0))),
        "increase_effort": bool(recommendation.get("increase_effort")),
        "reason_codes": [str(value)[:64] for value in (recommendation.get("reason_codes") or [])[:8]],
        "counterfactual": str(recommendation.get("counterfactual") or "")[:300],
    }


async def estimate_effort(
    db: Session,
    user_id: int,
    title: str,
    description: str = "",
    *,
    correlation_id: Optional[str] = None,
    quota_policy: Optional[LLMQuotaPolicy] = None,
) -> EffortEstimate:
    correlation_id = correlation_id or uuid.uuid4().hex
    policy = quota_policy or LLMQuotaPolicy()
    if not policy.allows_generation(db, user_id):
        return _fallback(correlation_id)

    messages = [
        {"role": "system", "content": SCHEDULE_ESTIMATION_SYSTEM_PROMPT},
        {"role": "user", "content": f"Title: {title[:255]}\nDescription: {(description or '')[:2000]}"},
    ]
    try:
        result = await ai_service.complete_once(
            messages,
            temperature=0.0,
            max_tokens=80,
        )
        hours, confidence = _parse(result.content)
        record_llm_usage(
            db,
            user_id=user_id,
            purpose="schedule_effort_estimation",
            provider=result.provider,
            model=result.model,
            outcome="succeeded",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            correlation_id=correlation_id,
        )
        db.commit()
        return EffortEstimate(
            estimated_hours=hours,
            confidence=confidence,
            source="llm",
            provider=result.provider,
            model=result.model,
            total_tokens=result.total_tokens,
            correlation_id=correlation_id,
        )
    except Exception:
        # Preserve the deterministic path and do not invent usage numbers when
        # the provider did not return usage metadata.
        db.rollback()
        return _fallback(correlation_id)


async def explain_recommendation(
    db: Session,
    user_id: int,
    recommendation: dict,
    *,
    language: str = "zh-CN",
    correlation_id: Optional[str] = None,
    quota_policy: Optional[LLMQuotaPolicy] = None,
) -> ScheduleExplanation:
    """Optionally phrase an immutable deterministic result in plain text."""
    correlation_id = correlation_id or uuid.uuid4().hex
    payload = _structured_explanation_payload(recommendation)
    fallback = deterministic_explanation(payload, language)
    policy = quota_policy or LLMQuotaPolicy()
    if not policy.allows_generation(db, user_id):
        return ScheduleExplanation(fallback, "template", correlation_id=correlation_id)

    messages = [
        {"role": "system", "content": SCHEDULE_EXPLANATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"language": str(language)[:16], "recommendation": payload},
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]
    try:
        result = await ai_service.complete_once(messages, temperature=0.0, max_tokens=120)
        text = " ".join((result.content or "").strip().split())[:600]
        if not text:
            raise ValueError("empty schedule explanation")
        record_llm_usage(
            db,
            user_id=user_id,
            purpose="schedule_explanation",
            provider=result.provider,
            model=result.model,
            outcome="succeeded",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            correlation_id=correlation_id,
        )
        db.commit()
        return ScheduleExplanation(
            text=text,
            source="llm",
            provider=result.provider,
            model=result.model,
            total_tokens=result.total_tokens,
            correlation_id=correlation_id,
        )
    except Exception:
        db.rollback()
        return ScheduleExplanation(fallback, "template", correlation_id=correlation_id)
