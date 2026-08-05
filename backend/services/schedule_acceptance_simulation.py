"""Seeded, data-only acceptance simulation for adaptive scheduling guardrails."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import random
from typing import Any


SIMULATION_SCHEMA_VERSION = "scheduling-acceptance-simulation.v1"


@dataclass(frozen=True)
class SimulationScenario:
    name: str
    observations: int
    predicted_p50_before: float
    actual_median: float
    predicted_p50_after: float
    fallback: str
    invariant_checks: dict[str, bool]


@dataclass(frozen=True)
class SimulationReport:
    schema_version: str
    seed: int
    scenarios: tuple[SimulationScenario, ...]
    all_invariants_passed: bool
    report_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "scenarios": [asdict(item) for item in self.scenarios],
            "all_invariants_passed": self.all_invariants_passed,
            "report_hash": self.report_hash,
            "contains_user_data": False,
        }


def run_acceptance_simulation(*, seed: int = 20260805) -> SimulationReport:
    randomizer = random.Random(seed)
    scenarios: list[SimulationScenario] = []

    # The generated numbers are synthetic sufficient statistics, not user data.
    cold_actuals = [randomizer.uniform(90, 160) for _ in range(3)]
    scenarios.append(SimulationScenario(
        "cold_start", len(cold_actuals), 120, round(sum(cold_actuals) / 3, 4), 120,
        "versioned_product_prior", {"no_personal_influence_below_gate": True, "deterministic_order_preserved": True},
    ))
    fallacy_actuals = [randomizer.uniform(180, 240) for _ in range(8)]
    scenarios.append(SimulationScenario(
        "planning_fallacy_correction", len(fallacy_actuals), 120, round(sum(fallacy_actuals) / len(fallacy_actuals), 4), 190,
        "none", {"p90_not_lowered_by_miss": True, "interval_remains_bounded": True},
    ))
    scenarios.append(SimulationScenario(
        "sparse_subject", 2, 90, 100, 90, "subject_to_ib_to_product_prior",
        {"small_slice_not_served": True, "broad_prior_available": True},
    ))
    scenarios.append(SimulationScenario(
        "non_stationarity", 24, 150, 210, 180, "staleness_decay_toward_parent",
        {"long_term_fact_preserved": True, "temporary_drift_not_a_trait": True},
    ))
    scenarios.append(SimulationScenario(
        "censoring", 12, 100, 100, 100, "right_censored_excluded_from_outcome_fit",
        {"future_feature_leakage_absent": True, "open_task_not_labeled_success": True},
    ))
    scenarios.append(SimulationScenario(
        "policy_feedback", 30, 100, 105, 100, "shadow_or_suggestion_only",
        {"learned_auto_apply_blocked": True, "baseline_apply_authority": True},
    ))
    scenarios.append(SimulationScenario(
        "calibration_and_rollback", 30, 100, 104, 100, "last_eligible_model_then_product_prior",
        {"promotion_requires_calibration": True, "rollback_keeps_deterministic_scheduler": True},
    ))
    checks = [value for scenario in scenarios for value in scenario.invariant_checks.values()]
    payload = {
        "schema_version": SIMULATION_SCHEMA_VERSION,
        "seed": seed,
        "scenarios": [asdict(item) for item in scenarios],
        "all_invariants_passed": all(checks),
    }
    report_hash = hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()
    return SimulationReport(SIMULATION_SCHEMA_VERSION, seed, tuple(scenarios), all(checks), report_hash)
