"""Versioned, deterministic policy for the energy-waterline scheduler."""

import os
from dataclasses import dataclass, asdict
from typing import Dict


ALGORITHM_VERSION = "energy-waterline-v1"
INTERVENTION_THRESHOLD = 3


@dataclass(frozen=True)
class PolicyProfile:
    name: str
    target_ratio: float
    overload_weight: float
    buffer_weight: float
    movement_weight: float
    variety_weight: float
    switching_weight: float
    chunking_weight: float


BALANCED = PolicyProfile(
    name="balanced",
    target_ratio=0.85,
    overload_weight=4.0,
    buffer_weight=1.0,
    movement_weight=0.7,
    variety_weight=1.2,
    switching_weight=0.8,
    chunking_weight=0.6,
)
CONSERVATIVE = PolicyProfile(
    name="conservative",
    target_ratio=0.70,
    overload_weight=5.5,
    buffer_weight=1.5,
    movement_weight=0.5,
    variety_weight=1.3,
    switching_weight=0.9,
    chunking_weight=0.7,
)
SPRINT = PolicyProfile(
    name="sprint",
    target_ratio=1.0,
    overload_weight=3.2,
    buffer_weight=0.5,
    movement_weight=1.0,
    variety_weight=1.0,
    switching_weight=0.7,
    chunking_weight=0.5,
)

PROFILES: Dict[str, PolicyProfile] = {
    profile.name: profile for profile in (CONSERVATIVE, BALANCED, SPRINT)
}

DEFAULT_PREFERENCES = {
    "default_capacity_hours": 4.0,
    "reserve_ratio": 0.20,
    "balanced_target_ratio": 0.85,
    "min_chunk_hours": 0.5,
    "max_chunk_hours": 2.0,
    "max_major_items_per_date": INTERVENTION_THRESHOLD,
    "same_kind_soft_limit": 2,
    "switching_soft_limit": 3,
    "no_deadline_horizon_days": 30,
    "auto_scheduling_enabled": False,
    "timezone": "Asia/Shanghai",
}

REASON_CODES = {
    "overload": "overload_after_reserve",
    "deadline": "deadline_slack_risk",
    "procrastination": "procrastination_pressure",
    "same_kind": "same_kind_saturation",
    "switching": "switching_excess",
    "movement": "protect_existing_plan",
    "fragmentation": "avoid_fragmentation",
    "buffer": "useful_deadline_buffer",
    "pace": "required_pace",
    "capacity": "capacity_deficit",
    "dependency": "dependency_constraint",
}


def profile_for(name: str | None) -> PolicyProfile:
    return PROFILES.get(name or "balanced", BALANCED)


def profile_snapshot(profile: PolicyProfile) -> dict:
    return {"algorithm_version": ALGORITHM_VERSION, **asdict(profile)}


def scheduling_enabled() -> bool:
    """Keep scheduling available by default; allow an explicit emergency opt-out."""
    return os.getenv("SCHEDULING_BALANCER_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def bounded_intensity(value: float | None) -> float:
    try:
        value = float(value if value is not None else 1.0)
    except (TypeError, ValueError):
        value = 1.0
    return min(2.0, max(0.5, value))


def bounded_effort(value: float | None, default: float = 1.0) -> float:
    try:
        value = float(default if value is None else value)
    except (TypeError, ValueError):
        value = default
    return min(24.0, max(0.0, value))
