"""Fail-closed serving envelope for pure adaptive scheduling annotations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from time import monotonic
from typing import Callable, Iterable, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingModelPrediction, SchedulingModelRegistry
from schemas.schedule_personalization import ModelLifecycle, ServingMode
from services.schedule_adaptive_ranking import (
    AdaptiveRankingError,
    AdaptiveRankingPolicy,
    AdaptiveRankingResult,
    LearnedCandidateSignal,
    SafeCandidateSnapshot,
    annotate_safe_candidates,
    apply_bounded_ranking,
)
from services.schedule_personalization_config import PersonalizationRuntimeConfig
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_personalization_operations import effective_operational_config


SERVING_SCHEMA_VERSION = "scheduling-personalization-serving.v1"
Predictor = Callable[[tuple[SafeCandidateSnapshot, ...]], Iterable[LearnedCandidateSignal]]


@dataclass(frozen=True)
class ServingResult:
    schema_version: str
    mode: ServingMode
    ranking: AdaptiveRankingResult
    latency_ms: int
    prediction_count: int
    fallback_reason: Optional[str]
    timed_out: bool


def _context_hash(value: str) -> str:
    normalized = value.strip()
    if len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized.lower()):
        return normalized.lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _run_bounded(predictor: Predictor, candidates: tuple[SafeCandidateSnapshot, ...], budget_ms: int):
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="schedule-personalization")
    future = executor.submit(predictor, candidates)
    try:
        return tuple(future.result(timeout=budget_ms / 1000.0))
    finally:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)


def _zero_result(candidates: tuple[SafeCandidateSnapshot, ...], reason: str) -> AdaptiveRankingResult:
    baseline = annotate_safe_candidates(candidates)
    return AdaptiveRankingResult(
        schema_version=baseline.schema_version,
        safe_candidates=baseline.safe_candidates,
        annotations=baseline.annotations,
        baseline_order=baseline.baseline_order,
        display_order=baseline.display_order,
        hard_fields_unchanged=True,
        fallback_reason=reason,
    )


def _model_is_eligible(
    model: Optional[SchedulingModelRegistry],
    *,
    user_id: int,
    mode: ServingMode,
    watermark: int,
) -> bool:
    if model is None:
        return False
    allowed = {ModelLifecycle.candidate.value, ModelLifecycle.shadow.value, ModelLifecycle.promoted.value}
    if mode in {ServingMode.shadow, ServingMode.suggestion}:
        allowed = {ModelLifecycle.promoted.value}
    return bool(
        model.user_id == user_id
        and model.lifecycle in allowed
        and model.invalidated_at is None
        and int(model.source_eligibility_watermark) == watermark
    )


def _log_predictions(
    db: Session,
    *,
    user_id: int,
    decision_point_id: Optional[str],
    context_hash: str,
    model: Optional[SchedulingModelRegistry],
    mode: ServingMode,
    ranking: AdaptiveRankingResult,
    latency_ms: int,
    consent_version: int,
    watermark: int,
    fallback_reason: Optional[str],
) -> int:
    if decision_point_id is not None:
        try:
            UUID(decision_point_id)
        except (TypeError, ValueError):
            decision_point_id = None
    count = 0
    with db.begin_nested():
        for item in ranking.annotations:
            contributions = {
                "schema_version": SERVING_SCHEMA_VERSION,
                "evidence_categories": list(item.evidence_categories),
                "fallback_reason": fallback_reason,
                "hard_fields_unchanged": True,
            }
            # The payload is generated locally from bounded enums/strings only.
            if len(json.dumps(contributions, separators=(",", ":")).encode("utf-8")) > 32_768:
                contributions = {"fallback_reason": "logging_payload_bounded"}
            db.add(SchedulingModelPrediction(
                prediction_id=str(uuid4()),
                user_id=user_id,
                decision_point_id=decision_point_id,
                model_registry_id=model.id if model is not None else None,
                context_hash=context_hash,
                prediction_type="candidate_rank",
                horizon_date=next(
                    candidate.local_date
                    for candidate in ranking.safe_candidates
                    if candidate.candidate_id == item.candidate_id
                ),
                p50=Decimal(item.estimate_p50_minutes) if item.estimate_p50_minutes is not None else None,
                p90=Decimal(item.estimate_p90_minutes) if item.estimate_p90_minutes is not None else None,
                probability=Decimal(str(item.completion_probability)) if item.completion_probability is not None else None,
                evidence_maturity=Decimal(str(round(item.maturity, 5))),
                calibration_state="calibrated" if item.calibration_factor >= 0.8 else "limited",
                feature_contributions=contributions,
                baseline_rank=item.baseline_rank,
                learned_rank=item.personalized_rank,
                learned_adjustment=Decimal(str(round(item.applied_adjustment, 6))),
                serving_mode=mode.value,
                latency_ms=max(0, min(latency_ms, 2_147_483_647)),
                consent_version=consent_version,
                eligibility_watermark=watermark,
            ))
            count += 1
        db.flush()
    return count


def serve_personalization(
    db: Session,
    *,
    user_id: int,
    candidates: Iterable[SafeCandidateSnapshot],
    predictor: Optional[Predictor],
    model: Optional[SchedulingModelRegistry],
    context_identity: str,
    config: PersonalizationRuntimeConfig,
    decision_point_id: Optional[str] = None,
) -> ServingResult:
    """Run bounded inference and log replayable annotations without mutation."""
    safe = tuple(candidates)
    baseline = annotate_safe_candidates(safe)
    config = effective_operational_config(db, config)
    mode = config.effective_serving_mode
    consent = get_or_create_private_consent(db, user_id)
    fallback_reason: Optional[str] = None
    timed_out = False
    started = monotonic()

    if mode == ServingMode.killed:
        fallback_reason = "global_kill_switch"
    elif mode == ServingMode.disabled:
        fallback_reason = "runtime_disabled"
    elif not consent.operational_personalization_enabled:
        fallback_reason = "consent_disabled"
    elif predictor is None:
        fallback_reason = "predictor_unavailable"
    elif not _model_is_eligible(
        model,
        user_id=user_id,
        mode=mode,
        watermark=int(consent.eligibility_watermark),
    ):
        fallback_reason = "model_ineligible"

    ranking = baseline
    if fallback_reason is None:
        try:
            signals = _run_bounded(predictor, safe, config.inference_latency_budget_ms)
            ranking = apply_bounded_ranking(
                safe,
                signals,
                policy=AdaptiveRankingPolicy(
                    minimum_eligible_decisions=config.ranking_decision_threshold,
                    serving_safety_budget=0.5,
                    maximum_score_adjustment=config.maximum_score_adjustment,
                    maximum_rank_displacement=config.maximum_rank_displacement,
                    near_tie_score_delta=config.near_tie_score_delta,
                ),
                display_personalized=mode == ServingMode.suggestion,
            )
        except FutureTimeout:
            timed_out = True
            fallback_reason = "inference_timeout"
        except (AdaptiveRankingError, AttributeError, TypeError, ValueError, OverflowError):
            fallback_reason = "corrupt_prediction"
        except Exception:
            fallback_reason = "inference_failure"
    if fallback_reason is not None:
        ranking = _zero_result(safe, fallback_reason)

    latency_ms = max(0, int(round((monotonic() - started) * 1000)))
    prediction_count = 0
    if mode not in {ServingMode.disabled, ServingMode.killed} and consent.operational_personalization_enabled:
        try:
            prediction_count = _log_predictions(
                db,
                user_id=user_id,
                decision_point_id=decision_point_id,
                context_hash=_context_hash(context_identity),
                model=model if _model_is_eligible(
                    model,
                    user_id=user_id,
                    mode=mode,
                    watermark=int(consent.eligibility_watermark),
                ) else None,
                mode=mode,
                ranking=ranking,
                latency_ms=latency_ms,
                consent_version=int(consent.version),
                watermark=int(consent.eligibility_watermark),
                fallback_reason=fallback_reason,
            )
        except Exception:
            # Analytical logging failure cannot block deterministic scheduling.
            prediction_count = 0
            fallback_reason = fallback_reason or "prediction_logging_failed"
    return ServingResult(
        schema_version=SERVING_SCHEMA_VERSION,
        mode=mode,
        ranking=ranking,
        latency_ms=latency_ms,
        prediction_count=prediction_count,
        fallback_reason=fallback_reason,
        timed_out=timed_out,
    )
