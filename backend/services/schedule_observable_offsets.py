"""Bounded observable scheduling offsets without a latent trait score."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Sequence


OBSERVABLE_OFFSETS_VERSION = "scheduling-observable-offsets.v1"


@dataclass(frozen=True)
class WeightedObservable:
    value: float
    weight: float = 1.0

    def validate(self, *, minimum: float, maximum: float) -> None:
        if not math.isfinite(self.value) or not minimum <= self.value <= maximum:
            raise ValueError("observable value is outside its bounded range")
        if not math.isfinite(self.weight) or not 0 < self.weight <= 1:
            raise ValueError("observable weight must be in (0, 1]")


@dataclass(frozen=True)
class ContextOutcome:
    overrun_ratio: float
    same_kind_run_length: int
    switch_count: int
    weight: float = 1.0

    def validate(self) -> None:
        if not math.isfinite(self.overrun_ratio) or not 0.05 <= self.overrun_ratio <= 20:
            raise ValueError("context outcome ratio is outside its bounded range")
        if not 0 <= self.same_kind_run_length <= 100 or not 0 <= self.switch_count <= 100:
            raise ValueError("context counts are outside bounded ranges")
        if not math.isfinite(self.weight) or not 0 < self.weight <= 1:
            raise ValueError("context weight must be in (0, 1]")


@dataclass(frozen=True)
class ObservableFactor:
    name: str
    offset: float
    lower_bound: float
    upper_bound: float
    evidence_count: int
    effective_sample_size: float
    status: str
    provenance: str
    eligible_use: str


@dataclass(frozen=True)
class ObservableOffsets:
    factors: tuple[ObservableFactor, ...]
    eligible_personal: bool
    version: str = OBSERVABLE_OFFSETS_VERSION

    def factor(self, name: str) -> ObservableFactor:
        return next(item for item in self.factors if item.name == name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "eligible_personal": self.eligible_personal,
            "factors": [asdict(item) for item in self.factors],
            "latent_trait_score": None,
        }


def _weighted_mean(values: Sequence[tuple[float, float]]) -> tuple[float, float]:
    total = sum(weight for _, weight in values)
    return (sum(value * weight for value, weight in values) / total, total) if total else (0.0, 0.0)


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _factor(
    name: str,
    raw_offset: float,
    bounds: tuple[float, float],
    values: Sequence[Any],
    effective_n: float,
    minimum_effective_n: float,
    eligible_use: str,
) -> ObservableFactor:
    sufficient = effective_n >= minimum_effective_n
    return ObservableFactor(
        name=name,
        offset=round(_clamp(raw_offset, *bounds), 8) if sufficient else 0.0,
        lower_bound=bounds[0],
        upper_bound=bounds[1],
        evidence_count=len(values),
        effective_sample_size=round(effective_n, 6),
        status="eligible" if sufficient else "insufficient_evidence",
        provenance="eligible_weighted_observations",
        eligible_use=eligible_use,
    )


def _comparison_factor(
    name: str,
    high: Sequence[ContextOutcome],
    low: Sequence[ContextOutcome],
    *,
    bound: float,
    minimum_group_effective_n: float,
    eligible_use: str,
) -> ObservableFactor:
    high_mean, high_n = _weighted_mean([(math.log(item.overrun_ratio), item.weight) for item in high])
    low_mean, low_n = _weighted_mean([(math.log(item.overrun_ratio), item.weight) for item in low])
    sufficient = high_n >= minimum_group_effective_n and low_n >= minimum_group_effective_n
    return ObservableFactor(
        name=name,
        offset=round(_clamp(high_mean - low_mean, -bound, bound), 8) if sufficient else 0.0,
        lower_bound=-bound,
        upper_bound=bound,
        evidence_count=len(high) + len(low),
        effective_sample_size=round(min(high_n, low_n), 6),
        status="eligible" if sufficient else "insufficient_comparison",
        provenance="eligible_within_user_context_comparison",
        eligible_use=eligible_use,
    )


def derive_observable_offsets(
    *,
    eligible_personal: bool,
    duration_overrun_ratios: Sequence[WeightedObservable] = (),
    initiation_delay_minutes: Sequence[WeightedObservable] = (),
    deferral_counts: Sequence[WeightedObservable] = (),
    optional_exertion_ratings: Sequence[WeightedObservable] = (),
    context_outcomes: Sequence[ContextOutcome] = (),
    minimum_effective_n: float = 5.0,
    minimum_comparison_group_n: float = 4.0,
) -> ObservableOffsets:
    if not 1 <= minimum_effective_n <= 100 or not 2 <= minimum_comparison_group_n <= 100:
        raise ValueError("observable evidence thresholds are invalid")
    for item in duration_overrun_ratios:
        item.validate(minimum=0.05, maximum=20)
    for item in initiation_delay_minutes:
        item.validate(minimum=0, maximum=100_800)
    for item in deferral_counts:
        item.validate(minimum=0, maximum=100)
    for item in optional_exertion_ratings:
        item.validate(minimum=1, maximum=5)
    for item in context_outcomes:
        item.validate()

    if not eligible_personal:
        duration_overrun_ratios = ()
        initiation_delay_minutes = ()
        deferral_counts = ()
        optional_exertion_ratings = ()
        context_outcomes = ()

    duration_mean, duration_n = _weighted_mean([
        (math.log(item.value), item.weight) for item in duration_overrun_ratios
    ])
    initiation_mean, initiation_n = _weighted_mean([
        (math.tanh((math.log1p(item.value) - math.log(61)) / 2), item.weight)
        for item in initiation_delay_minutes
    ])
    deferral_mean, deferral_n = _weighted_mean([
        (min(1.0, item.value / 5.0), item.weight) for item in deferral_counts
    ])
    exertion_mean, exertion_n = _weighted_mean([
        ((item.value - 3.0) / 2.0, item.weight) for item in optional_exertion_ratings
    ])
    same_high = [item for item in context_outcomes if item.same_kind_run_length >= 3]
    same_low = [item for item in context_outcomes if item.same_kind_run_length <= 1]
    switch_high = [item for item in context_outcomes if item.switch_count >= 3]
    switch_low = [item for item in context_outcomes if item.switch_count <= 1]

    factors = (
        _factor("duration_overrun", duration_mean, (-0.35, 0.35), duration_overrun_ratios, duration_n, minimum_effective_n, "effort_log_mean"),
        _factor("initiation_delay", initiation_mean * 0.20, (-0.20, 0.20), initiation_delay_minutes, initiation_n, minimum_effective_n, "completion_start_hazard"),
        _factor("deferral", (deferral_mean - 0.20) * 0.25, (-0.20, 0.20), deferral_counts, deferral_n, minimum_effective_n, "completion_start_hazard"),
        _factor("optional_exertion", exertion_mean * 0.15, (-0.15, 0.15), optional_exertion_ratings, exertion_n, minimum_effective_n, "displayed_load_annotation"),
        _comparison_factor(
            "same_kind_saturation", same_high, same_low,
            bound=0.15, minimum_group_effective_n=minimum_comparison_group_n,
            eligible_use="candidate_same_kind_penalty",
        ),
        _comparison_factor(
            "switching_sensitivity", switch_high, switch_low,
            bound=0.15, minimum_group_effective_n=minimum_comparison_group_n,
            eligible_use="candidate_switching_penalty",
        ),
    )
    return ObservableOffsets(factors=factors, eligible_personal=eligible_personal)

