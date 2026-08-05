"""Decision-value sensitivity analysis for at-most-one clarification.

This is a bounded EVSI proxy: it evaluates a small, explicit scenario set with
the unchanged deterministic scheduler and asks only when uncertainty changes a
safe action, deadline-risk band, overload band, or material split shape.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import math
from typing import Optional, Sequence

from services.schedule_engine import chunk_effort, recommend_date
from services.schedule_projection import ScheduleSnapshot, WorkItem
from services.schedule_taxonomy import EffortPrior


CLARIFICATION_POLICY_VERSION = "scheduling-clarification-evsi.v1"
DEFAULT_MATERIALITY_THRESHOLD = 0.25


@dataclass(frozen=True)
class SensitivityAssumption:
    label: str
    effort_hours: float
    probability: float
    resolves_fields: tuple[str, ...] = ("effort_hours",)
    scope_quantity: Optional[float] = None


@dataclass(frozen=True)
class SensitivityOutcome:
    label: str
    probability: float
    effort_hours: float
    feasible: bool
    recommended_date: Optional[date]
    requested_energy_ratio: Optional[float]
    requested_overloaded: bool
    split_packet_count: int
    deadline_risk_ratio: Optional[float]
    deadline_risk_band: str

    @property
    def action_key(self) -> str:
        return self.recommended_date.isoformat() if self.recommended_date else "infeasible"


@dataclass(frozen=True)
class ClarificationDecision:
    should_ask: bool
    question: Optional[str]
    unresolved_field: Optional[str]
    reason_code: str
    materiality_score: float
    decision_change_probability: float
    conservative_effort_hours: float
    scenario_outcomes: tuple[SensitivityOutcome, ...]
    material_changes: tuple[str, ...]
    policy_version: str = CLARIFICATION_POLICY_VERSION

    def to_dict(self) -> dict:
        return {
            "should_ask": self.should_ask,
            "question": self.question,
            "unresolved_field": self.unresolved_field,
            "reason_code": self.reason_code,
            "materiality_score": self.materiality_score,
            "decision_change_probability": self.decision_change_probability,
            "conservative_effort_hours": self.conservative_effort_hours,
            "material_changes": list(self.material_changes),
            "policy_version": self.policy_version,
            "scenarios": [
                {
                    "label": item.label,
                    "probability": item.probability,
                    "effort_hours": item.effort_hours,
                    "feasible": item.feasible,
                    "recommended_date": item.recommended_date.isoformat() if item.recommended_date else None,
                    "requested_energy_ratio": item.requested_energy_ratio,
                    "requested_overloaded": item.requested_overloaded,
                    "split_packet_count": item.split_packet_count,
                    "deadline_risk_ratio": item.deadline_risk_ratio,
                    "deadline_risk_band": item.deadline_risk_band,
                }
                for item in self.scenario_outcomes
            ],
        }


def assumptions_from_effort_prior(prior: EffortPrior) -> tuple[SensitivityAssumption, ...]:
    return (
        SensitivityAssumption("low", max(0.1, prior.p10_active_minutes / 60.0), 0.20),
        SensitivityAssumption("median", max(0.1, prior.p50_active_minutes / 60.0), 0.60),
        SensitivityAssumption("high", max(0.1, prior.p90_active_minutes / 60.0), 0.20),
    )


def _normalize_assumptions(values: Sequence[SensitivityAssumption]) -> tuple[SensitivityAssumption, ...]:
    if not 2 <= len(values) <= 5:
        raise ValueError("sensitivity analysis requires two to five assumptions")
    if len({item.label for item in values}) != len(values):
        raise ValueError("assumption labels must be unique")
    if any(not 0 < item.effort_hours <= 24 or item.probability < 0 for item in values):
        raise ValueError("assumptions must have bounded effort and non-negative probability")
    total = sum(item.probability for item in values)
    if total <= 0:
        raise ValueError("assumption probabilities must have positive mass")
    return tuple(replace(item, probability=item.probability / total) for item in values)


def _deadline_risk(snapshot: ScheduleSnapshot, item: WorkItem) -> tuple[Optional[float], str]:
    if item.hard_deadline_date is None:
        return None, "not_applicable"
    start = max(snapshot.local_today, item.earliest_start_date or snapshot.local_today)
    if item.hard_deadline_date < start:
        return float("inf"), "critical"
    available_energy = 0.0
    for offset in range((item.hard_deadline_date - start).days + 1):
        target = start + timedelta(days=offset)
        used = sum(peer.energy for peer in snapshot.items_on(target) if peer.key != item.key)
        available_energy += max(0.0, snapshot.usable_capacity_hours(target) - used)
    ratio = item.energy / available_energy if available_energy > 0 else float("inf")
    if ratio > 1.0:
        return ratio, "critical"
    if ratio > 0.70:
        return ratio, "warning"
    return ratio, "low"


def _evaluate(
    snapshot: ScheduleSnapshot,
    item: WorkItem,
    requested_date: date,
    assumption: SensitivityAssumption,
    profile: str,
) -> SensitivityOutcome:
    scenario_item = replace(item, estimated_hours=assumption.effort_hours, effort_source="sensitivity")
    recommendation = recommend_date(snapshot, scenario_item, requested_date, profile)
    usable = snapshot.usable_capacity_hours(requested_date)
    existing = sum(peer.energy for peer in snapshot.items_on(requested_date) if peer.key != item.key)
    projected = existing + scenario_item.energy
    ratio = projected / usable if usable > 0 else None
    risk_ratio, risk_band = _deadline_risk(snapshot, scenario_item)
    return SensitivityOutcome(
        label=assumption.label,
        probability=assumption.probability,
        effort_hours=assumption.effort_hours,
        feasible=recommendation.feasible,
        recommended_date=recommendation.recommended.date if recommendation.recommended else None,
        requested_energy_ratio=round(ratio, 6) if ratio is not None else None,
        requested_overloaded=usable <= 0 or projected > usable,
        split_packet_count=len(chunk_effort(
            assumption.effort_hours,
            minimum=snapshot.preferences.min_chunk_hours,
            maximum=snapshot.preferences.max_chunk_hours,
        )),
        deadline_risk_ratio=(
            round(risk_ratio, 6)
            if risk_ratio is not None and math.isfinite(risk_ratio)
            else None
        ),
        deadline_risk_band=risk_band,
    )


def _question_for(field: str, *, unit: Optional[str], locale: str) -> str:
    chinese = locale.casefold().startswith("zh")
    if field == "deliverable_quantity":
        label = unit or ("个交付单元" if chinese else "deliverable units")
        return f"为了判断是否需要拆分或换日期，这次大约要完成多少{label}？" if chinese else f"About how many {label} must be completed so I can tell whether to split or move it?"
    if field == "scope":
        return "为了判断是否需要拆分或换日期，这次具体要完成到哪个范围？" if chinese else "What exact scope must be completed so I can tell whether to split or move it?"
    return "为了判断是否需要拆分或换日期，你预计这项任务实际需要投入多少小时？" if chinese else "How many active hours do you expect this task to take so I can tell whether to split or move it?"


def analyze_clarification_value(
    snapshot: ScheduleSnapshot,
    item: WorkItem,
    requested_date: date,
    assumptions: Sequence[SensitivityAssumption],
    *,
    unresolved_fields: Sequence[str] = ("effort_hours",),
    deliverable_unit: Optional[str] = None,
    profile: str = "balanced",
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
    locale: str = "zh-CN",
) -> ClarificationDecision:
    if not 0 <= materiality_threshold <= 1:
        raise ValueError("materiality threshold must be between zero and one")
    scenarios = _normalize_assumptions(assumptions)
    outcomes = tuple(_evaluate(snapshot, item, requested_date, value, profile) for value in scenarios)

    action_mass: dict[str, float] = {}
    for outcome in outcomes:
        action_mass[outcome.action_key] = action_mass.get(outcome.action_key, 0.0) + outcome.probability
    decision_change_probability = 1.0 - max(action_mass.values())
    changes: list[str] = []
    score = 0.45 * decision_change_probability
    if len({item.action_key for item in outcomes}) > 1:
        changes.append("top_date_changes")
    if len({item.feasible for item in outcomes}) > 1:
        changes.append("feasibility_changes")
        score += 0.25
    if len({item.deadline_risk_band for item in outcomes}) > 1:
        changes.append("hard_deadline_risk_changes")
        score += 0.30
    if len({item.split_packet_count for item in outcomes}) > 1:
        changes.append("split_shape_changes")
        score += 0.25
    if len({item.requested_overloaded for item in outcomes}) > 1:
        changes.append("requested_date_overload_changes")
        score += 0.20
    score = round(min(1.0, score), 6)

    fields = tuple(dict.fromkeys(
        field
        for field in unresolved_fields
        if field in {candidate for scenario in scenarios for candidate in scenario.resolves_fields}
    ))
    # Prefer an objective count/scope answer over a subjective time guess when
    # both resolve the same scenarios; this lowers user burden without adding a
    # second question.
    priority = {"deliverable_quantity": 0, "scope": 1, "effort_hours": 2}
    selected_field = min(fields, key=lambda field: (priority.get(field, 9), field)) if fields else None
    should_ask = bool(changes and score >= materiality_threshold and selected_field)
    if should_ask:
        question = _question_for(selected_field, unit=deliverable_unit, locale=locale)
        reason_code = changes[0]
    elif not changes or score < materiality_threshold:
        question = None
        reason_code = "uncertainty_not_decision_material"
    else:
        question = None
        reason_code = "no_resolvable_question"
    return ClarificationDecision(
        should_ask=should_ask,
        question=question,
        unresolved_field=selected_field if should_ask else None,
        reason_code=reason_code,
        materiality_score=score,
        decision_change_probability=round(decision_change_probability, 6),
        conservative_effort_hours=max(item.effort_hours for item in outcomes),
        scenario_outcomes=outcomes,
        material_changes=tuple(changes),
    )
