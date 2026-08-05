"""Inspectable explanation projections for deterministic + learned scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from schemas.schedule_personalization import MemoryPurpose
from services.schedule_llm_memory import (
    ProviderCallable,
    build_bounded_llm_projection,
    run_bounded_llm_operation,
)


EXPLANATION_SCHEMA_VERSION = "scheduling-recommendation-explanation.v1"
_ALLOWED_EVIDENCE_CATEGORIES = frozenset({
    "active_timer",
    "direct_duration",
    "eligible_decision_history",
    "eligible_outcomes",
    "recent_decisions",
    "subject_history",
    "task_archetype_history",
})


@dataclass(frozen=True)
class ExplanationResult:
    structured: dict[str, Any]
    wording: dict[str, Any]
    used_provider: bool
    fallback_reason: Optional[str]
    audit: dict[str, Any]


def build_structured_explanation(
    recommendation: dict[str, Any],
    personalization: dict[str, Any],
    *,
    candidate_id: Optional[str] = None,
) -> dict[str, Any]:
    selected_id = candidate_id or f"date:{recommendation.get('date')}"
    annotations = {
        item.get("candidate_id"): item
        for item in personalization.get("annotations", [])
        if isinstance(item, dict) and item.get("candidate_id")
    }
    annotation = annotations.get(selected_id) or {}
    reason_codes = [
        str(item)[:64]
        for item in (recommendation.get("reason_codes") or [])[:12]
        if isinstance(item, str) and item
    ]
    categories = [
        item for item in (annotation.get("evidence_categories") or [])
        if item in _ALLOWED_EVIDENCE_CATEGORIES
    ][:8]
    p50 = annotation.get("estimate_p50_minutes")
    p90 = annotation.get("estimate_p90_minutes")
    maturity = max(0.0, min(1.0, float(annotation.get("maturity") or 0)))
    calibration = max(0.0, min(1.0, float(annotation.get("calibration_factor") or 0)))
    baseline_rank = int(annotation.get("baseline_rank") or recommendation.get("baseline_rank") or 1)
    personalized_rank = int(annotation.get("personalized_rank") or baseline_rank)
    adjustment = float(annotation.get("learned_adjustment") or 0)
    serving_mode = str(personalization.get("serving_mode") or "disabled")
    learned_used = bool(personalization.get("model_version") and adjustment != 0)
    if p50 is not None and p90 is not None and p50 > p90:
        p50 = p90 = None
    limitations = []
    if not personalization.get("model_version"):
        limitations.append("当前没有兼容的个性化模型，建议保持确定性基线。")
    if maturity < 0.5:
        limitations.append("可用个人证据较少，个性化影响为零或很小。")
    if calibration < 0.6:
        limitations.append("当前校准证据不足，不应把概率或时长当作精确值。")
    if personalization.get("fallback_reason"):
        limitations.append("个性化不可用时已自动回退到确定性排序。")
    return {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "candidate_id": selected_id,
        "deterministic": {
            "date": recommendation.get("date"),
            "baseline_rank": baseline_rank,
            "baseline_score": recommendation.get("score"),
            "reason_codes": reason_codes,
            "hard_constraints": ["capacity", "deadline", "dependencies", "locks"],
            "authority": "feasibility_and_apply",
        },
        "personalization": {
            "serving_mode": serving_mode,
            "model_version": personalization.get("model_version"),
            "evidence_categories": categories,
            "maturity": round(maturity, 6),
            "maturity_state": "established" if maturity >= 0.8 else ("developing" if maturity >= 0.5 else "low_data"),
            "calibration_factor": round(calibration, 6),
            "calibration_state": "calibrated" if calibration >= 0.8 else ("limited" if calibration >= 0.6 else "insufficient"),
            "baseline_rank": baseline_rank,
            "personalized_rank": personalized_rank,
            "learned_adjustment": adjustment,
            "influenced_display": learned_used and serving_mode == "suggestion",
            "can_auto_apply": False,
        },
        "estimate_range": {
            "p50_minutes": p50,
            "p90_minutes": p90,
            "interpretation": "P50 是中位估计，P90 是保守上界估计；两者都不是承诺。" if p50 and p90 else None,
        },
        "uncertainty": {
            "limitations": limitations,
            "fallback_reason": personalization.get("fallback_reason"),
            "causal_claim": False,
            "psychological_trait_inference": False,
        },
        "alternatives": {
            "baseline_order": list(personalization.get("baseline_order") or []),
            "display_order": list(personalization.get("display_order") or []),
            "user_can_choose_any_safe_candidate": True,
        },
    }


async def project_explanation(
    db: Session,
    user_id: int,
    *,
    current_task: dict[str, Any],
    recommendation: dict[str, Any],
    personalization: dict[str, Any],
    provider: Optional[ProviderCallable] = None,
) -> ExplanationResult:
    structured = build_structured_explanation(recommendation, personalization)
    deterministic_context = {
        "selected_date": structured["deterministic"]["date"],
        "deterministic_reason_codes": structured["deterministic"]["reason_codes"],
        "hard_constraints": structured["deterministic"]["hard_constraints"],
        "uncertainty": structured["uncertainty"],
        "personal_evidence": structured["personalization"]["evidence_categories"],
        "estimate_range": structured["estimate_range"],
        "calibration": structured["personalization"]["calibration_state"],
        "maturity": structured["personalization"]["maturity_state"],
        "baseline_rank": structured["personalization"]["baseline_rank"],
        "personalized_rank": structured["personalization"]["personalized_rank"],
        "learned_adjustment": structured["personalization"]["learned_adjustment"],
        "serving_mode": structured["personalization"]["serving_mode"],
    }
    projection = build_bounded_llm_projection(
        db,
        user_id,
        purpose=MemoryPurpose.explanation,
        current_task=current_task,
        deterministic_context=deterministic_context,
        subject=current_task.get("subject"),
        task_archetype=current_task.get("task_archetype"),
    )
    result = await run_bounded_llm_operation(
        projection,
        purpose=MemoryPurpose.explanation,
        deterministic_context=deterministic_context,
        provider=provider,
    )
    return ExplanationResult(
        structured=structured,
        wording=result.output,
        used_provider=result.used_provider,
        fallback_reason=result.fallback_reason,
        audit=result.audit,
    )
