"""Private-by-default runtime policy for adaptive scheduling.

The loader is pure and accepts an explicit mapping so tests and workers share
exactly the same environment semantics.  Unknown or malformed values always
fall back toward deterministic behavior.
"""

from dataclasses import dataclass
import os
from typing import Mapping, Optional

from schemas.schedule_personalization import ServingMode


def _safe_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return False


def _bounded_int(
    value: Optional[str],
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if minimum <= parsed <= maximum else default


def _bounded_float(
    value: Optional[str],
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if minimum <= parsed <= maximum else default


@dataclass(frozen=True)
class PersonalizationRuntimeConfig:
    master_enabled: bool = False
    observation_capture_enabled: bool = False
    modeling_enabled: bool = False
    shadow_enabled: bool = False
    suggestion_enabled: bool = False
    reflection_enabled: bool = False
    cross_user_aggregation_enabled: bool = False
    exploration_enabled: bool = False
    kill_switch: bool = False
    raw_event_retention_days: int = 365
    effort_observation_threshold: int = 5
    ranking_decision_threshold: int = 20
    inference_latency_budget_ms: int = 75
    maximum_score_adjustment: float = 0.25
    maximum_rank_displacement: int = 1
    near_tie_score_delta: float = 0.10
    feature_refresh_interval_seconds: int = 86_400
    model_refresh_interval_seconds: int = 604_800
    reflection_interval_seconds: int = 604_800

    @property
    def effective_serving_mode(self) -> ServingMode:
        if self.kill_switch:
            return ServingMode.killed
        if not self.master_enabled or not self.modeling_enabled:
            return ServingMode.disabled
        if self.suggestion_enabled:
            return ServingMode.suggestion
        if self.shadow_enabled:
            return ServingMode.shadow
        return ServingMode.replay

    @property
    def effective_capture_enabled(self) -> bool:
        return self.master_enabled and self.observation_capture_enabled and not self.kill_switch

    @property
    def effective_reflection_enabled(self) -> bool:
        return self.master_enabled and self.reflection_enabled and not self.kill_switch

    @property
    def effective_cross_user_enabled(self) -> bool:
        return self.master_enabled and self.cross_user_aggregation_enabled and not self.kill_switch

    @property
    def effective_exploration_enabled(self) -> bool:
        return (
            self.effective_serving_mode == ServingMode.suggestion
            and self.exploration_enabled
            and not self.kill_switch
        )


def load_personalization_runtime_config(
    environ: Optional[Mapping[str, str]] = None,
) -> PersonalizationRuntimeConfig:
    values = os.environ if environ is None else environ
    return PersonalizationRuntimeConfig(
        master_enabled=_safe_bool(values.get("SCHEDULING_PERSONALIZATION_ENABLED")),
        observation_capture_enabled=_safe_bool(values.get("SCHEDULING_OBSERVATION_CAPTURE_ENABLED")),
        modeling_enabled=_safe_bool(values.get("SCHEDULING_PERSONAL_MODELING_ENABLED")),
        shadow_enabled=_safe_bool(values.get("SCHEDULING_PERSONALIZATION_SHADOW_ENABLED")),
        suggestion_enabled=_safe_bool(values.get("SCHEDULING_PERSONALIZATION_SUGGESTION_ENABLED")),
        reflection_enabled=_safe_bool(values.get("SCHEDULING_MEMORY_REFLECTION_ENABLED")),
        cross_user_aggregation_enabled=_safe_bool(values.get("SCHEDULING_CROSS_USER_AGGREGATION_ENABLED")),
        exploration_enabled=_safe_bool(values.get("SCHEDULING_NEAR_TIE_EXPLORATION_ENABLED")),
        kill_switch=_safe_bool(values.get("SCHEDULING_PERSONALIZATION_KILL_SWITCH")),
        raw_event_retention_days=_bounded_int(
            values.get("SCHEDULING_RAW_EVENT_RETENTION_DAYS"), default=365, minimum=30, maximum=3650
        ),
        effort_observation_threshold=_bounded_int(
            values.get("SCHEDULING_EFFORT_OBSERVATION_THRESHOLD"), default=5, minimum=1, maximum=100
        ),
        ranking_decision_threshold=_bounded_int(
            values.get("SCHEDULING_RANKING_DECISION_THRESHOLD"), default=20, minimum=1, maximum=1000
        ),
        inference_latency_budget_ms=_bounded_int(
            values.get("SCHEDULING_PERSONALIZATION_LATENCY_MS"), default=75, minimum=5, maximum=2000
        ),
        maximum_score_adjustment=_bounded_float(
            values.get("SCHEDULING_MAXIMUM_SCORE_ADJUSTMENT"), default=0.25, minimum=0, maximum=1
        ),
        maximum_rank_displacement=_bounded_int(
            values.get("SCHEDULING_MAXIMUM_RANK_DISPLACEMENT"), default=1, minimum=0, maximum=3
        ),
        near_tie_score_delta=_bounded_float(
            values.get("SCHEDULING_NEAR_TIE_SCORE_DELTA"), default=0.10, minimum=0, maximum=1
        ),
        feature_refresh_interval_seconds=_bounded_int(
            values.get("SCHEDULING_FEATURE_REFRESH_SECONDS"), default=86_400, minimum=60, maximum=2_592_000
        ),
        model_refresh_interval_seconds=_bounded_int(
            values.get("SCHEDULING_MODEL_REFRESH_SECONDS"), default=604_800, minimum=300, maximum=7_776_000
        ),
        reflection_interval_seconds=_bounded_int(
            values.get("SCHEDULING_REFLECTION_INTERVAL_SECONDS"), default=604_800, minimum=300, maximum=7_776_000
        ),
    )


personalization_runtime_config = load_personalization_runtime_config()
