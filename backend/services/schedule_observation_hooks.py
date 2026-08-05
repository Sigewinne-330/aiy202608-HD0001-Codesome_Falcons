"""Failure-isolated adapters from deterministic scheduling to observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
from typing import Iterable, Optional
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from models.scheduling import ScheduleIntervention, SchedulePlan, SchedulePlanItem, SchedulingPreference
from schemas.schedule_personalization import DecisionObservationInput
from services.schedule_observations import canonical_context_hash, capture_decision_observation
from services.schedule_personalization_config import (
    PersonalizationRuntimeConfig,
    personalization_runtime_config,
)
from services.schedule_policy import ALGORITHM_VERSION


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObservationHookStatus:
    state: str
    captured: int = 0
    excluded: int = 0


def _local_clock(db: Session, user_id: int) -> tuple[datetime, date, str]:
    preference = db.query(SchedulingPreference).filter_by(user_id=user_id).one_or_none()
    timezone_name = preference.timezone if preference and preference.timezone else "Asia/Shanghai"
    now = datetime.now(timezone.utc)
    return now, now.astimezone(ZoneInfo(timezone_name)).date(), timezone_name


def _candidate(
    candidate_id: str,
    local_date: date,
    rank: int,
    score: float,
    reason_codes: Iterable[str],
    effort_hours: float,
    energy_points: float,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "local_date": local_date,
        "deterministic_rank": rank,
        "deterministic_score": score,
        "reason_codes": list(reason_codes)[:20],
        "effort_hours": max(0.0, float(effort_hours or 0)),
        "energy_points": max(0.0, float(energy_points or 0)),
    }


def _capture_batch(
    db: Session,
    user_id: int,
    observations: list[DecisionObservationInput],
    *,
    config: PersonalizationRuntimeConfig,
) -> ObservationHookStatus:
    if not config.effective_capture_enabled:
        return ObservationHookStatus(state="disabled")
    captured = 0
    excluded = 0
    try:
        for observation in observations:
            result = capture_decision_observation(db, user_id, observation, capture_enabled=True)
            if result.event is not None:
                captured += int(result.created)
            elif result.skipped_reason:
                excluded += 1
        db.commit()
        return ObservationHookStatus(
            state="captured" if captured else "excluded",
            captured=captured,
            excluded=excluded,
        )
    except Exception as exc:
        db.rollback()
        logger.warning(
            "schedule_observation_capture_failed user_id=%s observation_count=%s error_type=%s",
            user_id,
            len(observations),
            type(exc).__name__,
        )
        return ObservationHookStatus(state="failed", excluded=len(observations))


def capture_intervention_resolution_after_commit(
    db: Session,
    user_id: int,
    intervention: ScheduleIntervention,
    source_type: str,
    source_id: int,
    selected_date: date,
    decision: str,
    *,
    config: Optional[PersonalizationRuntimeConfig] = None,
) -> ObservationHookStatus:
    ranked = list(intervention.ranked_recommendations or [])
    if not ranked:
        ranked = [{
            "date": intervention.target_date.isoformat(),
            "score": 0,
            "reason_codes": ["keep_requested_date"],
            "recommended_effort_hours": 0,
            "projected_energy": 0,
        }]
    candidates = []
    for index, value in enumerate(ranked[:30], start=1):
        candidate_date = date.fromisoformat(value["date"])
        candidates.append(_candidate(
            f"date:{candidate_date.isoformat()}",
            candidate_date,
            index,
            value.get("score", 0),
            value.get("reason_codes", []),
            value.get("recommended_effort_hours", 0),
            value.get("projected_energy", 0),
        ))
    selected_id = f"date:{selected_date.isoformat()}"
    listed_ids = {value["candidate_id"] for value in candidates}
    selection_source = "user" if selected_id in listed_ids else "user_unlisted"
    displayed = sorted(
        zip(ranked[:30], candidates),
        key=lambda pair: int(pair[0].get("display_rank") or pair[1]["deterministic_rank"]),
    )
    randomized_assignment = any(bool(value.get("randomized_assignment")) for value in ranked)
    propensity = next(
        (value.get("assignment_probability") for value in ranked if value.get("assignment_probability") is not None),
        None,
    )
    model_version = next((value.get("model_version") for value in ranked if value.get("model_version")), None)
    assignment_denominator = next(
        (value.get("assignment_denominator") for value in ranked if value.get("assignment_denominator")),
        None,
    )
    now, local_today, timezone_name = _local_clock(db, user_id)
    context = {
        "algorithm_version": ALGORITHM_VERSION,
        "decision_kind": "intervention_resolution",
        "input_revision": intervention.input_revision,
        "intervention_id": intervention.id,
        "overload_count": intervention.projected_count,
        "requested_date": intervention.target_date.isoformat(),
        "selected_date": selected_date.isoformat(),
        "trigger": decision,
        "assignment_probability": (
            {"numerator": 1, "denominator": int(assignment_denominator)}
            if randomized_assignment and assignment_denominator else None
        ),
    }
    observation = DecisionObservationInput(
        decision_point_id=uuid5(NAMESPACE_URL, f"schedule-intervention:{user_id}:{intervention.id}"),
        idempotency_key=f"intervention:{intervention.id}:resolution",
        correlation_id=intervention.correlation_id,
        source={"source_type": source_type, "source_id": source_id},
        occurred_at=now,
        local_date=local_today,
        timezone=timezone_name,
        context_hash=canonical_context_hash(context),
        context_snapshot=context,
        candidates=candidates,
        displayed_candidate_ids=[candidate["candidate_id"] for _, candidate in displayed[:10]],
        selected_candidate_id=selected_id,
        selection_source=selection_source,
        randomized_assignment=randomized_assignment,
        action_propensity=propensity if randomized_assignment else None,
        policy_version=ALGORITHM_VERSION,
        model_version=model_version,
    )
    return _capture_batch(
        db,
        user_id,
        [observation],
        config=config or personalization_runtime_config,
    )


def _plan_observations(
    db: Session,
    user_id: int,
    plan: SchedulePlan,
    plan_items: Iterable[SchedulePlanItem],
    *,
    phase: str,
    actor: str = "user",
) -> list[DecisionObservationInput]:
    now, local_today, timezone_name = _local_clock(db, user_id)
    observations = []
    for item in plan_items:
        candidate_date = item.after_date or item.before_date or local_today
        candidate_id = f"date:{candidate_date.isoformat()}"
        context = {
            "algorithm_version": plan.algorithm_version,
            "decision_kind": f"plan_{phase}",
            "input_revision": plan.input_revision,
            "plan_id": plan.id,
            "policy_profile": plan.profile,
            "selected_date": candidate_date.isoformat() if phase == "apply" else None,
            "source_schedule_version": item.before_version,
            "trigger": actor,
        }
        observations.append(DecisionObservationInput(
            decision_point_id=uuid5(
                NAMESPACE_URL,
                f"schedule-plan:{user_id}:{plan.id}:{phase}:{item.source_type}:{item.source_id}",
            ),
            idempotency_key=f"plan:{plan.id}:{phase}:{item.source_type}:{item.source_id}",
            source={"source_type": item.source_type, "source_id": item.source_id},
            occurred_at=now,
            local_date=local_today,
            timezone=timezone_name,
            context_hash=canonical_context_hash(context),
            context_snapshot=context,
            candidates=[_candidate(
                candidate_id,
                candidate_date,
                1,
                float(item.score or 0),
                item.reason_codes or [],
                float(item.effort_hours or 0),
                float(item.effort_hours or 0),
            )],
            displayed_candidate_ids=[candidate_id],
            selected_candidate_id=candidate_id if phase == "apply" else None,
            selection_source=("deterministic_auto" if actor == "system" else "user") if phase == "apply" else "unknown",
            automation_mode="deterministic_auto" if phase == "apply" and actor == "system" else "manual",
            policy_version=plan.algorithm_version,
        ))
    return observations


def capture_plan_preview_after_commit(
    db: Session,
    user_id: int,
    plan: SchedulePlan,
    plan_items: Iterable[SchedulePlanItem],
    *,
    config: Optional[PersonalizationRuntimeConfig] = None,
) -> ObservationHookStatus:
    return _capture_batch(
        db,
        user_id,
        _plan_observations(db, user_id, plan, plan_items, phase="preview"),
        config=config or personalization_runtime_config,
    )


def capture_plan_apply_after_commit(
    db: Session,
    user_id: int,
    plan: SchedulePlan,
    plan_items: Iterable[SchedulePlanItem],
    *,
    actor: str,
    config: Optional[PersonalizationRuntimeConfig] = None,
) -> ObservationHookStatus:
    return _capture_batch(
        db,
        user_id,
        _plan_observations(db, user_id, plan, plan_items, phase="apply", actor=actor),
        config=config or personalization_runtime_config,
    )
