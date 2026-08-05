"""Censoring-aware, date-level completion hazard model.

The implementation is deliberately small and auditable: bounded observable
features, a regularized logistic hazard, explicit at-risk rows, temporal
cutoffs, and a static prior fallback when evidence is insufficient.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
import hashlib
import json
import math
from typing import Any, Iterable, Optional, Sequence


RISK_MODEL_ALGORITHM_VERSION = "scheduling-completion-hazard.v1"
RISK_FEATURE_SCHEMA_VERSION = "scheduling-risk-feature.v1"
FEATURE_NAMES = (
    "intercept",
    "remaining_effort",
    "effort_uncertainty",
    "deadline_proximity",
    "progress",
    "deferrals",
    "projected_load",
    "dependency_blocked",
    "priority",
    "split_complexity",
)
PRIOR_COEFFICIENTS = {
    "intercept": -1.40,
    "remaining_effort": -1.00,
    "effort_uncertainty": -0.35,
    "deadline_proximity": 0.75,
    "progress": 1.25,
    "deferrals": -0.45,
    "projected_load": -0.65,
    "dependency_blocked": -1.25,
    "priority": 0.35,
    "split_complexity": -0.25,
}
_TERMINAL_STATES = {"completed", "reasonably_abandoned", "confirmed_miss", "deleted", "unknown"}
_PRIORITY = {"low": 0.75, "medium": 1.0, "high": 1.35, "urgent": 1.8}


@dataclass(frozen=True)
class RiskFeatureSnapshot:
    local_date: date
    available_at: date
    remaining_effort_p50_minutes: float
    remaining_effort_p90_minutes: float
    slack_days: Optional[int]
    progress_ratio: float
    deferral_count: int
    projected_energy_ratio: float
    dependency_blocked: bool
    split_packet_count: int
    priority: str = "medium"
    feature_schema_version: str = RISK_FEATURE_SCHEMA_VERSION

    def validate(self) -> None:
        if self.feature_schema_version != RISK_FEATURE_SCHEMA_VERSION:
            raise ValueError("unsupported risk feature schema")
        if self.available_at > self.local_date:
            raise ValueError("feature was not available on its modeled date")
        if not 0 <= self.remaining_effort_p50_minutes <= self.remaining_effort_p90_minutes <= 100_800:
            raise ValueError("effort quantiles are invalid")
        if not 0 <= self.progress_ratio <= 1 or not 0 <= self.deferral_count <= 10_000:
            raise ValueError("progress or deferral count is invalid")
        if not 0 <= self.projected_energy_ratio <= 100 or not 0 <= self.split_packet_count <= 10_000:
            raise ValueError("load or split count is invalid")
        if self.priority not in _PRIORITY:
            raise ValueError("priority is invalid")

    def vector(self) -> dict[str, float]:
        self.validate()
        p50_hours = self.remaining_effort_p50_minutes / 60.0
        spread_hours = max(0.0, self.remaining_effort_p90_minutes - self.remaining_effort_p50_minutes) / 60.0
        proximity = 0.0 if self.slack_days is None else 1.0 / (1.0 + max(0, self.slack_days))
        return {
            "intercept": 1.0,
            "remaining_effort": min(2.0, math.log1p(p50_hours) / 3.0),
            "effort_uncertainty": min(2.0, math.log1p(spread_hours) / 3.0),
            "deadline_proximity": proximity,
            "progress": self.progress_ratio,
            "deferrals": min(1.0, self.deferral_count / 5.0),
            "projected_load": min(2.0, self.projected_energy_ratio / 1.5),
            "dependency_blocked": 1.0 if self.dependency_blocked else 0.0,
            "priority": _PRIORITY[self.priority] / 1.8,
            "split_complexity": min(1.0, max(0, self.split_packet_count - 1) / 5.0),
        }


@dataclass(frozen=True)
class RiskEpisode:
    episode_id: str
    feature_snapshots: tuple[RiskFeatureSnapshot, ...]
    terminal_state: str
    terminal_date: Optional[date]
    observation_cutoff: date

    def validate(self) -> None:
        if not self.episode_id or len(self.episode_id) > 128:
            raise ValueError("episode ID is invalid")
        if self.terminal_state not in _TERMINAL_STATES:
            raise ValueError("terminal state is invalid")
        if self.terminal_state in {"completed", "reasonably_abandoned", "confirmed_miss", "deleted"} and self.terminal_date is None:
            raise ValueError("terminal date is required for a terminal episode")
        dates = [item.local_date for item in self.feature_snapshots]
        if len(dates) != len(set(dates)):
            raise ValueError("episode contains duplicate date snapshots")
        for item in self.feature_snapshots:
            item.validate()


@dataclass(frozen=True)
class RiskTrainingRow:
    episode_id: str
    local_date: date
    features: dict[str, float]
    completed_on_date: int


@dataclass(frozen=True)
class CompletionRiskModel:
    coefficients: dict[str, float]
    training_cutoff: date
    training_row_count: int
    completion_event_count: int
    censored_episode_count: int
    fit_status: str
    calibration_state: str
    feature_schema_version: str
    algorithm_version: str
    model_version: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["training_cutoff"] = self.training_cutoff.isoformat()
        return value


@dataclass(frozen=True)
class RiskEvaluation:
    row_count: int
    completion_event_count: int
    brier_score: Optional[float]
    expected_calibration_error: Optional[float]
    calibration_bins: tuple[dict[str, Any], ...]
    calibration_state: str
    evaluation_start: date
    evaluation_cutoff: date


@dataclass(frozen=True)
class CompletionRiskPrediction:
    probability_by_horizon: float
    horizon_date: date
    daily_hazards: tuple[dict[str, Any], ...]
    dominant_observable_factors: tuple[str, ...]
    calibration_state: str
    fit_status: str
    model_version: str


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-min(50.0, value))
        return 1.0 / (1.0 + z)
    z = math.exp(max(-50.0, value))
    return z / (1.0 + z)


def _hazard(coefficients: dict[str, float], features: dict[str, float]) -> float:
    return _sigmoid(sum(coefficients[name] * features[name] for name in FEATURE_NAMES))


def expand_risk_episodes(
    episodes: Iterable[RiskEpisode],
    *,
    cutoff: date,
    start_date: Optional[date] = None,
) -> tuple[RiskTrainingRow, ...]:
    rows: list[RiskTrainingRow] = []
    for episode in episodes:
        episode.validate()
        if episode.terminal_state == "deleted":
            continue
        effective_cutoff = min(cutoff, episode.observation_cutoff)
        terminal_stop = episode.terminal_date if episode.terminal_date and episode.terminal_date <= effective_cutoff else effective_cutoff
        for snapshot in sorted(episode.feature_snapshots, key=lambda item: item.local_date):
            if snapshot.available_at > cutoff:
                raise ValueError("future feature leakage detected")
            if snapshot.local_date > effective_cutoff or snapshot.local_date > terminal_stop:
                continue
            if start_date and snapshot.local_date < start_date:
                continue
            completed = int(
                episode.terminal_state == "completed"
                and episode.terminal_date == snapshot.local_date
                and episode.terminal_date <= effective_cutoff
            )
            rows.append(RiskTrainingRow(
                episode_id=episode.episode_id,
                local_date=snapshot.local_date,
                features=snapshot.vector(),
                completed_on_date=completed,
            ))
    return tuple(rows)


def _version(coefficients: dict[str, float], payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"coefficients": coefficients, **payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{RISK_MODEL_ALGORITHM_VERSION}:{hashlib.sha256(raw).hexdigest()[:20]}"


def fit_completion_risk_model(
    episodes: Sequence[RiskEpisode],
    *,
    training_cutoff: date,
    minimum_rows: int = 20,
    minimum_events: int = 5,
    regularization: float = 0.25,
    learning_rate: float = 0.08,
    iterations: int = 500,
) -> CompletionRiskModel:
    if not 5 <= minimum_rows <= 100_000 or not 1 <= minimum_events <= minimum_rows:
        raise ValueError("training evidence thresholds are invalid")
    if not 0 < regularization <= 10 or not 0 < learning_rate <= 1 or not 10 <= iterations <= 5_000:
        raise ValueError("fitting policy is invalid")
    rows = expand_risk_episodes(episodes, cutoff=training_cutoff)
    events = sum(row.completed_on_date for row in rows)
    censored = sum(
        1 for item in episodes
        if item.terminal_state == "unknown" or item.terminal_date is None or item.terminal_date > training_cutoff
    )
    coefficients = dict(PRIOR_COEFFICIENTS)
    fit_status = "prior_fallback"
    if len(rows) >= minimum_rows and events >= minimum_events:
        for _ in range(iterations):
            gradient = {name: 0.0 for name in FEATURE_NAMES}
            for row in rows:
                error = _hazard(coefficients, row.features) - row.completed_on_date
                for name in FEATURE_NAMES:
                    gradient[name] += error * row.features[name]
            for name in FEATURE_NAMES:
                average = gradient[name] / len(rows)
                penalty = regularization * (coefficients[name] - PRIOR_COEFFICIENTS[name])
                coefficients[name] = min(6.0, max(-6.0, coefficients[name] - learning_rate * (average + penalty)))
        coefficients = {name: round(coefficients[name], 10) for name in FEATURE_NAMES}
        fit_status = "personal_candidate"
    payload = {
        "training_cutoff": training_cutoff.isoformat(),
        "rows": len(rows),
        "events": events,
        "censored": censored,
        "fit_status": fit_status,
        "feature_schema_version": RISK_FEATURE_SCHEMA_VERSION,
    }
    return CompletionRiskModel(
        coefficients=coefficients,
        training_cutoff=training_cutoff,
        training_row_count=len(rows),
        completion_event_count=events,
        censored_episode_count=censored,
        fit_status=fit_status,
        calibration_state="prior_only" if fit_status == "prior_fallback" else "unevaluated",
        feature_schema_version=RISK_FEATURE_SCHEMA_VERSION,
        algorithm_version=RISK_MODEL_ALGORITHM_VERSION,
        model_version=_version(coefficients, payload),
    )


def predict_completion_by_horizon(
    model: CompletionRiskModel,
    snapshots: Sequence[RiskFeatureSnapshot],
    *,
    prediction_cutoff: date,
    horizon_date: date,
) -> CompletionRiskPrediction:
    if horizon_date < prediction_cutoff:
        raise ValueError("horizon cannot precede prediction cutoff")
    ordered = sorted(snapshots, key=lambda item: item.local_date)
    if len({item.local_date for item in ordered}) != len(ordered):
        raise ValueError("prediction snapshots must have unique dates")
    survival = 1.0
    daily = []
    contributions = {name: 0.0 for name in FEATURE_NAMES if name != "intercept"}
    for snapshot in ordered:
        snapshot.validate()
        if snapshot.available_at > prediction_cutoff:
            raise ValueError("future feature leakage detected")
        if snapshot.local_date < prediction_cutoff or snapshot.local_date > horizon_date:
            continue
        features = snapshot.vector()
        hazard = _hazard(model.coefficients, features)
        survival *= 1.0 - hazard
        cumulative = 1.0 - survival
        daily.append({
            "date": snapshot.local_date.isoformat(),
            "hazard": round(hazard, 8),
            "completion_by_date": round(cumulative, 8),
        })
        for name in contributions:
            contributions[name] += abs(model.coefficients[name] * features[name])
    dominant = tuple(
        name for name, value in sorted(contributions.items(), key=lambda item: (-item[1], item[0]))
        if value > 0
    )[:4]
    return CompletionRiskPrediction(
        probability_by_horizon=round(1.0 - survival, 8),
        horizon_date=horizon_date,
        daily_hazards=tuple(daily),
        dominant_observable_factors=dominant,
        calibration_state=model.calibration_state,
        fit_status=model.fit_status,
        model_version=model.model_version,
    )


def evaluate_risk_calibration(
    model: CompletionRiskModel,
    episodes: Sequence[RiskEpisode],
    *,
    evaluation_start: date,
    evaluation_cutoff: date,
    minimum_rows: int = 20,
    minimum_events: int = 5,
) -> RiskEvaluation:
    if evaluation_start <= model.training_cutoff:
        raise ValueError("evaluation must be strictly future-only")
    if evaluation_cutoff < evaluation_start:
        raise ValueError("evaluation cutoff precedes evaluation start")
    rows = expand_risk_episodes(episodes, cutoff=evaluation_cutoff, start_date=evaluation_start)
    scored = [(_hazard(model.coefficients, row.features), row.completed_on_date) for row in rows]
    events = sum(outcome for _, outcome in scored)
    if not scored:
        return RiskEvaluation(0, 0, None, None, (), "insufficient", evaluation_start, evaluation_cutoff)
    brier = sum((probability - outcome) ** 2 for probability, outcome in scored) / len(scored)
    bins = []
    weighted_gap = 0.0
    for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
        upper = lower + 0.2
        members = [(p, y) for p, y in scored if lower <= p < upper or (upper >= 1 and p == 1)]
        if not members:
            continue
        predicted = sum(p for p, _ in members) / len(members)
        observed = sum(y for _, y in members) / len(members)
        gap = abs(predicted - observed)
        weighted_gap += gap * len(members) / len(scored)
        bins.append({
            "lower": lower,
            "upper": min(1.0, upper),
            "count": len(members),
            "mean_predicted": round(predicted, 8),
            "observed_rate": round(observed, 8),
        })
    if len(scored) < minimum_rows or events < minimum_events:
        state = "insufficient"
    elif weighted_gap <= 0.15 and brier <= 0.25:
        state = "calibrated"
    else:
        state = "miscalibrated"
    return RiskEvaluation(
        row_count=len(scored),
        completion_event_count=events,
        brier_score=round(brier, 8),
        expected_calibration_error=round(weighted_gap, 8),
        calibration_bins=tuple(bins),
        calibration_state=state,
        evaluation_start=evaluation_start,
        evaluation_cutoff=evaluation_cutoff,
    )


def attach_calibration_state(model: CompletionRiskModel, evaluation: RiskEvaluation) -> CompletionRiskModel:
    payload = {
        "base_model_version": model.model_version,
        "calibration_state": evaluation.calibration_state,
        "evaluation_start": evaluation.evaluation_start.isoformat(),
        "evaluation_cutoff": evaluation.evaluation_cutoff.isoformat(),
        "brier_score": evaluation.brier_score,
        "expected_calibration_error": evaluation.expected_calibration_error,
    }
    updated = replace(model, calibration_state=evaluation.calibration_state)
    return replace(updated, model_version=_version(updated.coefficients, payload))

