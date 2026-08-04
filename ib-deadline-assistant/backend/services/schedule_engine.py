"""Pure deterministic energy-waterline scheduling engine."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from services.schedule_policy import (
    ALGORITHM_VERSION,
    INTERVENTION_THRESHOLD,
    PolicyProfile,
    profile_for,
)
from services.schedule_projection import (
    DependencyEdge,
    ScheduleSnapshot,
    WorkItem,
    serialize_item,
)


@dataclass(frozen=True)
class Candidate:
    date: date
    projected_count: int
    projected_hours: float
    projected_energy: float
    capacity_hours: float
    usable_capacity_hours: float
    energy_ratio: float
    score: float
    terms: Dict[str, float]
    weights: Dict[str, float]
    recommended_effort_hours: float
    increase_effort: bool
    reason_codes: Tuple[str, ...] = ()
    counterfactual: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "projected_count": self.projected_count,
            "projected_hours": round(self.projected_hours, 4),
            "projected_energy": round(self.projected_energy, 4),
            "capacity_hours": round(self.capacity_hours, 4),
            "usable_capacity_hours": round(self.usable_capacity_hours, 4),
            "energy_ratio": round(self.energy_ratio, 6),
            "score": round(self.score, 8),
            "score_breakdown": {
                "terms": {key: round(value, 8) for key, value in sorted(self.terms.items())},
                "weights": {key: round(value, 8) for key, value in sorted(self.weights.items())},
                "total": round(self.score, 8),
            },
            "recommended_effort_hours": round(self.recommended_effort_hours, 4),
            "increase_effort": self.increase_effort,
            "reason_codes": list(self.reason_codes),
            "counterfactual": self.counterfactual,
        }


@dataclass(frozen=True)
class RecommendationResult:
    feasible: bool
    requested_date: date
    recommended: Optional[Candidate]
    alternatives: Tuple[Candidate, ...] = ()
    blockers: Tuple[str, ...] = ()
    complete_day: Tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "algorithm_version": ALGORITHM_VERSION,
            "feasible": self.feasible,
            "requested_date": self.requested_date.isoformat(),
            "recommendation": self.recommended.to_dict() if self.recommended else None,
            "alternatives": [item.to_dict() for item in self.alternatives],
            "blockers": list(self.blockers),
            "complete_day": list(self.complete_day),
        }


@dataclass(frozen=True)
class Placement:
    item_key: str
    before_date: Optional[date]
    after_date: Optional[date]
    score: float
    reason_codes: Tuple[str, ...]
    effort_hours: float
    before_version: int
    chunks: Tuple[Tuple[date, float], ...] = ()

    def to_dict(self) -> dict:
        return {
            "source_type": self.item_key.split(":", 1)[0],
            "source_id": int(self.item_key.split(":", 1)[1]),
            "before_date": self.before_date.isoformat() if self.before_date else None,
            "after_date": self.after_date.isoformat() if self.after_date else None,
            "score": round(self.score, 8),
            "reason_codes": list(self.reason_codes),
            "effort_hours": round(self.effort_hours, 4),
            "before_version": self.before_version,
            "chunks": [
                {"date": chunk_date.isoformat(), "effort_hours": round(hours, 4)}
                for chunk_date, hours in self.chunks
            ],
        }


@dataclass(frozen=True)
class RebalanceResult:
    feasible: bool
    profile: str
    placements: Tuple[Placement, ...]
    daily_loads: Tuple[dict, ...]
    blockers: Tuple[str, ...] = ()
    capacity_deficit_hours: float = 0.0
    earliest_feasible_completion_date: Optional[date] = None
    affected_items: Tuple[str, ...] = ()


def chunk_effort(total_hours: float, minimum: float = 0.5, maximum: float = 2.0) -> Tuple[float, ...]:
    """Split effort into bounded packets with at most one small remainder."""
    total = max(0.0, float(total_hours))
    minimum = max(0.01, float(minimum))
    maximum = max(minimum, float(maximum))
    if total <= maximum:
        return (round(total, 6),) if total else ()
    full_count = int(total // maximum)
    remainder = round(total - full_count * maximum, 6)
    chunks = [maximum] * full_count
    if remainder:
        chunks.append(remainder)
    # When the remainder is below the minimum, keep it as the one bounded
    # remainder.  This avoids manufacturing extra work or exceeding the total.
    return tuple(round(value, 6) for value in chunks if value > 0)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, value))


def _items_on(snapshot: ScheduleSnapshot, target: date, excluded_key: Optional[str] = None) -> List[WorkItem]:
    return [
        item for item in snapshot.items
        if item.local_date == target and item.key != excluded_key
    ]


def projected_count(snapshot: ScheduleSnapshot, target: date, proposed: Optional[WorkItem] = None) -> int:
    keys = {item.key for item in snapshot.items_on(target)}
    if proposed:
        keys.add(proposed.key)
    return len(keys)


def _dependency_map(edges: Iterable[DependencyEdge]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for edge in edges:
        result.setdefault(edge.successor, []).append(edge.predecessor)
    return result


def _work_units(items: Iterable[WorkItem]) -> Dict[str, WorkItem]:
    """Aggregate allocation packets into one movable source-level work unit."""
    units: Dict[str, WorkItem] = {}
    for item in sorted(
        items,
        key=lambda row: (row.key, row.local_date or date.min, row.metadata.get("allocation_id") or 0),
    ):
        existing = units.get(item.key)
        if existing is None:
            units[item.key] = item
            continue
        dates = [value for value in (existing.local_date, item.local_date) if value is not None]
        units[item.key] = replace(
            existing,
            local_date=min(dates) if dates else None,
            estimated_hours=round(existing.estimated_hours + item.estimated_hours, 6),
            metadata={**existing.metadata, "aggregated_allocations": True},
        )
    return units


def _effective_profile(
    snapshot: ScheduleSnapshot,
    profile: str | PolicyProfile,
) -> PolicyProfile:
    selected = profile if isinstance(profile, PolicyProfile) else profile_for(profile)
    if selected.name == "balanced":
        return replace(selected, target_ratio=snapshot.preferences.balanced_target_ratio)
    return selected


def dependency_order(snapshot: ScheduleSnapshot) -> Tuple[List[WorkItem], List[str]]:
    items_by_key = _work_units(snapshot.items)
    predecessors = _dependency_map(snapshot.dependencies)
    indegree = {key: 0 for key in items_by_key}
    outgoing: Dict[str, List[str]] = {}
    for successor, parents in predecessors.items():
        if successor not in items_by_key:
            continue
        for parent in parents:
            if parent not in items_by_key:
                continue
            indegree[successor] += 1
            outgoing.setdefault(parent, []).append(successor)

    def order_key(key: str):
        item = items_by_key[key]
        return (-item.priority_weight, item.hard_deadline_date or date.max, -item.energy, key)

    ready = sorted((key for key, count in indegree.items() if count == 0), key=order_key)
    ordered: List[WorkItem] = []
    while ready:
        key = ready.pop(0)
        ordered.append(items_by_key[key])
        for successor in sorted(outgoing.get(key, [])):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
                ready.sort(key=order_key)

    if len(ordered) != len(items_by_key):
        cycle_nodes = sorted(key for key, count in indegree.items() if count > 0)
        return ordered, [f"dependency_cycle:{','.join(cycle_nodes)}"]

    # Kahn's ready-queue order already applies the stable criticality tie-break
    # while preserving every dependency edge.
    return ordered, []


def hard_constraint_reason(
    snapshot: ScheduleSnapshot,
    item: WorkItem,
    target: date,
    *,
    existing_assignments: Optional[Dict[str, date]] = None,
) -> Optional[str]:
    if target < snapshot.local_today and item.local_date != target:
        return "past_date"
    if item.earliest_start_date and target < item.earliest_start_date:
        return "earliest_start"
    if item.hard_deadline_date and target > item.hard_deadline_date:
        return "hard_deadline"
    if snapshot.capacity_hours(target) <= 0:
        return "zero_capacity"
    if item.is_schedule_locked and item.local_date != target:
        return "locked_item"

    predecessors = _dependency_map(snapshot.dependencies).get(item.key, [])
    for predecessor in predecessors:
        predecessor_item = next((candidate for candidate in snapshot.items if candidate.key == predecessor), None)
        if not predecessor_item:
            return "missing_dependency"
        assigned = (existing_assignments or {}).get(predecessor, predecessor_item.local_date)
        if assigned and target < assigned:
            return "dependency_order"
    return None


def _normal_weights(profile: PolicyProfile) -> Dict[str, float]:
    return {
        "overload_after": profile.overload_weight,
        "deadline_slack_risk": 3.0,
        "procrastination_pressure": 1.5,
        "same_kind_saturation": profile.variety_weight,
        "switching_excess": profile.switching_weight,
        "movement_cost": profile.movement_weight,
        "fragmentation_cost": profile.chunking_weight,
        "useful_buffer_gain": profile.buffer_weight,
    }


def _candidate_terms(
    snapshot: ScheduleSnapshot,
    item: WorkItem,
    target: date,
    profile: PolicyProfile,
    *,
    existing_assignments: Optional[Dict[str, date]] = None,
    exclude_existing_key: bool = True,
    peers_override: Optional[Sequence[WorkItem]] = None,
) -> Candidate:
    peers = list(peers_override) if peers_override is not None else _items_on(
        snapshot,
        target,
        excluded_key=item.key if exclude_existing_key else None,
    )
    projected_hours = sum(peer.estimated_hours for peer in peers) + item.estimated_hours
    projected_energy = sum(peer.energy for peer in peers) + item.energy
    capacity_hours = snapshot.capacity_hours(target)
    usable_hours = snapshot.usable_capacity_hours(target)
    energy_ratio = projected_energy / usable_hours if usable_hours > 0 else 1.0
    ratio_over_target = max(0.0, energy_ratio - profile.target_ratio)
    overload = _clamp(ratio_over_target / max(0.25, 1.0 - min(profile.target_ratio, 0.95)))

    if item.hard_deadline_date:
        days_left = max(0, (item.hard_deadline_date - target).days)
        slack_risk = _clamp(item.energy / max(0.5, usable_hours * (days_left + 1)))
    else:
        slack_risk = 0.0

    window_start = item.earliest_start_date or snapshot.local_today
    window_end = item.hard_deadline_date or (window_start + timedelta(days=snapshot.preferences.no_deadline_horizon_days))
    total_window = max(1, (window_end - window_start).days + 1)
    elapsed = _clamp((target - window_start).days / total_window)
    procrastination = _clamp(
        0.45 * elapsed + 0.35 * (1.0 - item.progress / 100.0) + 0.20 * min(1.0, item.deferral_count / 3.0)
    )

    same_kind_count = sum(peer.schedule_kind == item.schedule_kind for peer in peers)
    same_kind = _clamp(max(0, same_kind_count - snapshot.preferences.same_kind_soft_limit + 1) / 3.0)
    distinct_kinds = len({peer.schedule_kind for peer in peers} | {item.schedule_kind})
    switching = _clamp(max(0, distinct_kinds - snapshot.preferences.switching_soft_limit) / 3.0)

    if item.local_date:
        movement = _clamp(abs((target - item.local_date).days) / max(1, total_window))
    else:
        movement = 0.0
    fragmentation = _clamp(0.35 if item.estimated_hours < snapshot.preferences.min_chunk_hours else 0.0)
    buffer_gain = _clamp(
        max(0, ((item.hard_deadline_date - target).days if item.hard_deadline_date else 0)) / max(1, total_window)
    )

    terms = {
        "overload_after": overload * overload,
        "deadline_slack_risk": slack_risk,
        "procrastination_pressure": procrastination,
        "same_kind_saturation": same_kind,
        "switching_excess": switching,
        "movement_cost": movement,
        "fragmentation_cost": fragmentation,
        "useful_buffer_gain": buffer_gain,
    }
    weights = _normal_weights(profile)
    score = sum(weights[name] * terms[name] for name in terms if name != "useful_buffer_gain")
    score -= weights["useful_buffer_gain"] * terms["useful_buffer_gain"]

    used_energy = sum(peer.energy for peer in peers)
    headroom = max(0.0, usable_hours - used_energy) / max(0.5, item.energy_intensity)
    remaining_days = max(1, (window_end - snapshot.local_today).days + 1)
    required_pace = item.estimated_hours / remaining_days
    planned_pace = item.estimated_hours / max(1, remaining_days + item.deferral_count)
    recommended = min(
        item.estimated_hours,
        snapshot.preferences.max_chunk_hours,
        headroom,
        max(snapshot.preferences.min_chunk_hours, required_pace),
    )
    recommended = max(0.0, recommended)
    increase_effort = bool(
        recommended > 0
        and required_pace > planned_pace + 0.25
        and headroom >= required_pace
    )

    reasons: List[str] = []
    if overload > 0:
        reasons.append("overload_after_reserve")
    if slack_risk > 0.35:
        reasons.append("deadline_slack_risk")
    if procrastination > 0.55:
        reasons.append("procrastination_pressure")
    if same_kind > 0:
        reasons.append("same_kind_saturation")
    if switching > 0:
        reasons.append("switching_excess")
    if movement > 0:
        reasons.append("protect_existing_plan")
    if buffer_gain > 0.25:
        reasons.append("useful_deadline_buffer")
    if increase_effort:
        reasons.append("required_pace")
    if not reasons:
        reasons.append("balanced_capacity")

    return Candidate(
        date=target,
        projected_count=len({peer.key for peer in peers} | {item.key}),
        projected_hours=projected_hours,
        projected_energy=projected_energy,
        capacity_hours=capacity_hours,
        usable_capacity_hours=usable_hours,
        energy_ratio=energy_ratio,
        score=round(score, 8),
        terms=terms,
        weights=weights,
        recommended_effort_hours=round(recommended, 4),
        increase_effort=increase_effort,
        reason_codes=tuple(reasons),
    )


def _candidate_dates(snapshot: ScheduleSnapshot, item: WorkItem, requested_date: date) -> List[date]:
    start = max(snapshot.local_today, item.earliest_start_date or snapshot.local_today)
    end = item.hard_deadline_date or (start + timedelta(days=snapshot.preferences.no_deadline_horizon_days))
    if end < start:
        return []
    dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    if requested_date not in dates and requested_date >= start and requested_date <= end:
        dates.append(requested_date)
    return sorted(set(dates))


def recommend_date(
    snapshot: ScheduleSnapshot,
    item: WorkItem,
    requested_date: date,
    profile: str | PolicyProfile = "balanced",
) -> RecommendationResult:
    selected_profile = _effective_profile(snapshot, profile)
    complete_day = tuple(serialize_item(candidate) for candidate in snapshot.items_on(requested_date))
    candidates: List[Candidate] = []
    blockers: List[str] = []
    for target in _candidate_dates(snapshot, item, requested_date):
        hard_reason = hard_constraint_reason(snapshot, item, target)
        if hard_reason:
            if hard_reason not in blockers:
                blockers.append(hard_reason)
            continue
        candidates.append(_candidate_terms(snapshot, item, target, selected_profile))

    candidates.sort(key=lambda candidate: (candidate.score, candidate.date, item.key))
    if not candidates:
        return RecommendationResult(
            feasible=False,
            requested_date=requested_date,
            recommended=None,
            blockers=tuple(sorted(blockers)) or ("no_feasible_date",),
            complete_day=complete_day,
        )

    best = candidates[0]
    requested_candidate = next((candidate for candidate in candidates if candidate.date == requested_date), None)
    if requested_candidate and requested_candidate.score <= best.score:
        best = requested_candidate

    alternatives = [candidate for candidate in candidates if candidate.date != best.date][:3]
    if requested_candidate and best.date != requested_date:
        keep_load = f"保留 {requested_date.isoformat()}：{requested_candidate.energy_ratio:.0%} 负载"
        move_load = f"移动到 {best.date.isoformat()}：{best.energy_ratio:.0%} 负载"
        gain = max(0, (requested_candidate.energy_ratio - best.energy_ratio))
        best = Candidate(**{**best.__dict__, "counterfactual": f"{keep_load}；{move_load}；预计降低 {gain:.0%} 能量比"})

    return RecommendationResult(
        feasible=True,
        requested_date=requested_date,
        recommended=best,
        alternatives=tuple(alternatives),
        blockers=tuple(sorted(blockers)),
        complete_day=complete_day,
    )


def analyze_dates(
    snapshot: ScheduleSnapshot,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Tuple[List[dict], List[str]]:
    start = start_date or snapshot.local_today
    end = end_date or (start + timedelta(days=snapshot.preferences.no_deadline_horizon_days))
    if end < start:
        return [], ["invalid_date_range"]
    rows = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        items = snapshot.items_on(day)
        hours = sum(item.estimated_hours for item in items)
        energy = sum(item.energy for item in items)
        usable = snapshot.usable_capacity_hours(day)
        rows.append({
            "date": day.isoformat(),
            "item_count": len({item.key for item in items}),
            "hours": round(hours, 4),
            "energy": round(energy, 4),
            "capacity_hours": round(snapshot.capacity_hours(day), 4),
            "usable_capacity_hours": round(usable, 4),
            "energy_ratio": round(energy / usable, 6) if usable > 0 else None,
            "overloaded": usable <= 0 or energy > usable,
            "item_keys": [item.key for item in sorted(items, key=lambda row: row.key)],
        })
    return rows, []


def bounded_local_improvement(
    snapshot: ScheduleSnapshot,
    placements: Sequence[Placement],
    profile: str | PolicyProfile = "balanced",
    max_iterations: int = 24,
    max_evaluations: int = 512,
) -> Tuple[Placement, ...]:
    """Improve packet placements with deterministic bounded moves and swaps.

    The search never invents work or relaxes a hard constraint.  It operates
    only on the already feasible greedy result and stops after fixed iteration
    and evaluation budgets, which keeps runtime predictable for Agent calls.
    """
    selected_profile = _effective_profile(snapshot, profile)
    source_map = _work_units(snapshot.items)

    def materialized(candidate_placements: Sequence[Placement]) -> ScheduleSnapshot:
        moved_keys = {placement.item_key for placement in candidate_placements}
        items = [item for item in snapshot.items if item.key not in moved_keys]
        for placement in candidate_placements:
            source = source_map.get(placement.item_key)
            if not source:
                continue
            chunks = placement.chunks or (
                ((placement.after_date, placement.effort_hours),)
                if placement.after_date else ()
            )
            for packet_index, (packet_date, packet_hours) in enumerate(chunks):
                items.append(replace(
                    source,
                    local_date=packet_date,
                    estimated_hours=packet_hours,
                    effort_source="plan",
                    metadata={**source.metadata, "packet_index": packet_index},
                ))
        return ScheduleSnapshot(
            user_id=snapshot.user_id,
            items=tuple(items),
            dependencies=snapshot.dependencies,
            preferences=snapshot.preferences,
            capacity_overrides=snapshot.capacity_overrides,
            revision=snapshot.revision,
        )

    def assignment_dates(candidate_placements: Sequence[Placement]) -> Dict[str, date]:
        assigned = {
            item.key: item.local_date
            for item in snapshot.items
            if item.local_date and item.key not in {placement.item_key for placement in candidate_placements}
        }
        for placement in candidate_placements:
            dates = [packet_date for packet_date, _ in placement.chunks]
            if dates:
                assigned[placement.item_key] = max(dates)
        return assigned

    def valid(candidate_placements: Sequence[Placement]) -> bool:
        candidate_snapshot = materialized(candidate_placements)
        assigned = assignment_dates(candidate_placements)
        for day in {item.local_date for item in candidate_snapshot.items if item.local_date}:
            energy = sum(item.energy for item in candidate_snapshot.items_on(day))
            if energy > candidate_snapshot.usable_capacity_hours(day) + 1e-8:
                return False
        for placement in candidate_placements:
            source = source_map.get(placement.item_key)
            if not source:
                return False
            if abs(sum(hours for _, hours in placement.chunks) - placement.effort_hours) > 1e-6:
                return False
            for packet_date, _ in placement.chunks:
                if hard_constraint_reason(
                    candidate_snapshot,
                    source,
                    packet_date,
                    existing_assignments=assigned,
                ):
                    return False
        return True

    def objective(candidate_placements: Sequence[Placement]) -> float:
        candidate_snapshot = materialized(candidate_placements)
        total = 0.0
        for placement in candidate_placements:
            source = source_map[placement.item_key]
            for packet_index, (packet_date, packet_hours) in enumerate(placement.chunks):
                packet = replace(source, estimated_hours=packet_hours)
                peers = []
                removed = False
                for peer in candidate_snapshot.items_on(packet_date):
                    if (
                        not removed
                        and peer.key == placement.item_key
                        and peer.metadata.get("packet_index") == packet_index
                    ):
                        removed = True
                        continue
                    peers.append(peer)
                total += _candidate_terms(
                    candidate_snapshot,
                    packet,
                    packet_date,
                    selected_profile,
                    peers_override=peers,
                ).score
        return round(total, 8)

    def replace_packet(
        values: Sequence[Placement],
        placement_index: int,
        packet_index: int,
        target: date,
    ) -> Tuple[Placement, ...]:
        result = list(values)
        placement = result[placement_index]
        chunks = list(placement.chunks)
        chunks[packet_index] = (target, chunks[packet_index][1])
        chunks.sort(key=lambda value: (value[0], value[1]))
        result[placement_index] = replace(
            placement,
            after_date=chunks[0][0],
            chunks=tuple(chunks),
        )
        return tuple(result)

    improved = tuple(placements)
    if not improved or not valid(improved):
        return improved
    current_score = objective(improved)
    evaluations = 0

    for _ in range(max(0, max_iterations)):
        best = improved
        best_score = current_score

        # Deterministic single-packet moves.
        for placement_index, placement in enumerate(improved):
            source = source_map.get(placement.item_key)
            if not source:
                continue
            for packet_index, (current_date, _) in enumerate(placement.chunks):
                for target in _candidate_dates(snapshot, source, current_date):
                    if target == current_date or evaluations >= max_evaluations:
                        continue
                    evaluations += 1
                    candidate = replace_packet(improved, placement_index, packet_index, target)
                    if not valid(candidate):
                        continue
                    candidate_score = objective(candidate)
                    if candidate_score + 1e-8 < best_score:
                        best, best_score = candidate, candidate_score

        # Deterministic pair swaps retain packet effort and only exchange dates.
        packet_refs = [
            (placement_index, packet_index, packet_date)
            for placement_index, placement in enumerate(improved)
            for packet_index, (packet_date, _) in enumerate(placement.chunks)
        ]
        for left_index, (lp, lc, left_date) in enumerate(packet_refs):
            for rp, rc, right_date in packet_refs[left_index + 1:]:
                if left_date == right_date or evaluations >= max_evaluations:
                    continue
                evaluations += 1
                candidate = replace_packet(improved, lp, lc, right_date)
                candidate = replace_packet(candidate, rp, rc, left_date)
                if not valid(candidate):
                    continue
                candidate_score = objective(candidate)
                if candidate_score + 1e-8 < best_score:
                    best, best_score = candidate, candidate_score

        if best == improved or best_score + 1e-8 >= current_score:
            break
        improved, current_score = best, best_score
        if evaluations >= max_evaluations:
            break

    # Refresh persisted scores/reasons against the final materialized load.
    final_snapshot = materialized(improved)
    refreshed: List[Placement] = []
    for placement in improved:
        source = source_map[placement.item_key]
        packet_scores = []
        for packet_index, (packet_date, hours) in enumerate(placement.chunks):
            peers = []
            removed = False
            for peer in final_snapshot.items_on(packet_date):
                if (
                    not removed
                    and peer.key == placement.item_key
                    and peer.metadata.get("packet_index") == packet_index
                ):
                    removed = True
                    continue
                peers.append(peer)
            packet_scores.append(_candidate_terms(
                final_snapshot,
                replace(source, estimated_hours=hours),
                packet_date,
                selected_profile,
                peers_override=peers,
            ))
        reasons = tuple(sorted({reason for candidate in packet_scores for reason in candidate.reason_codes}))
        refreshed.append(replace(
            placement,
            score=round(sum(candidate.score for candidate in packet_scores), 8),
            reason_codes=reasons,
        ))
    return tuple(refreshed)


def _earliest_completion_date(
    snapshot: ScheduleSnapshot,
    item: WorkItem,
    dynamic_items: Sequence[WorkItem],
    remaining_hours: float,
    start: date,
    *,
    max_days: int = 365,
) -> Optional[date]:
    """Find the first date cumulative free energy can absorb remaining work."""
    remaining_energy = max(0.0, remaining_hours * item.energy_intensity)
    for offset in range(max_days + 1):
        target = start + timedelta(days=offset)
        if item.earliest_start_date and target < item.earliest_start_date:
            continue
        if snapshot.capacity_hours(target) <= 0:
            continue
        used = sum(peer.energy for peer in dynamic_items if peer.local_date == target)
        remaining_energy -= max(0.0, snapshot.usable_capacity_hours(target) - used)
        if remaining_energy <= 1e-8:
            return target
    return None


def rebalance(
    snapshot: ScheduleSnapshot,
    profile: str | PolicyProfile = "balanced",
) -> RebalanceResult:
    selected_profile = _effective_profile(snapshot, profile)
    ordered, cycle_errors = dependency_order(snapshot)
    if cycle_errors:
        return RebalanceResult(False, selected_profile.name, (), (), tuple(cycle_errors))

    assignments = {
        item.key: item.local_date
        for item in snapshot.items
        if item.local_date and (item.is_schedule_locked or not item.flexible)
    }
    dynamic_items: List[WorkItem] = [
        item for item in snapshot.items
        if item.is_schedule_locked or not item.flexible or not item.local_date
    ]
    placements: List[Placement] = []
    blockers: List[str] = []
    affected_items: List[str] = []
    total_deficit_hours = 0.0
    earliest_completion: Optional[date] = None
    for item in ordered:
        if not item.local_date or item.is_schedule_locked or not item.flexible:
            continue
        packets = chunk_effort(
            item.estimated_hours,
            snapshot.preferences.min_chunk_hours,
            snapshot.preferences.max_chunk_hours,
        )
        item_chunks: List[Tuple[date, float]] = []
        item_candidates: List[Candidate] = []
        remaining_hours = sum(packets)
        candidate_dates = _candidate_dates(snapshot, item, item.local_date)

        for packet_index, packet_hours in enumerate(packets):
            packet = replace(
                item,
                estimated_hours=packet_hours,
                effort_source="plan",
                metadata={**item.metadata, "packet_index": packet_index},
            )
            dynamic_snapshot = ScheduleSnapshot(
                user_id=snapshot.user_id,
                items=tuple(dynamic_items),
                dependencies=snapshot.dependencies,
                preferences=snapshot.preferences,
                capacity_overrides=snapshot.capacity_overrides,
                revision=snapshot.revision,
            )
            feasible_candidates: List[Candidate] = []
            for target in candidate_dates:
                reason = hard_constraint_reason(
                    dynamic_snapshot,
                    packet,
                    target,
                    existing_assignments=assignments,
                )
                if reason:
                    continue
                used_energy = sum(peer.energy for peer in dynamic_items if peer.local_date == target)
                if used_energy + packet.energy > dynamic_snapshot.usable_capacity_hours(target) + 1e-8:
                    continue
                feasible_candidates.append(_candidate_terms(
                    dynamic_snapshot,
                    packet,
                    target,
                    selected_profile,
                    existing_assignments=assignments,
                    exclude_existing_key=False,
                ))
            feasible_candidates.sort(key=lambda candidate: (candidate.score, candidate.date, item.key, packet_index))
            if not feasible_candidates:
                deficit = max(0.0, remaining_hours)
                total_deficit_hours += deficit
                affected_items.append(item.key)
                blockers.append(f"capacity_deficit:{item.key}:{deficit:.4f}")
                calculated = _earliest_completion_date(
                    snapshot,
                    item,
                    dynamic_items,
                    remaining_hours,
                    max(snapshot.local_today, item.earliest_start_date or snapshot.local_today),
                )
                if calculated and (earliest_completion is None or calculated > earliest_completion):
                    earliest_completion = calculated
                break

            chosen = feasible_candidates[0]
            item_candidates.append(chosen)
            item_chunks.append((chosen.date, packet_hours))
            dynamic_items.append(replace(packet, local_date=chosen.date))
            remaining_hours = max(0.0, remaining_hours - packet_hours)

        if remaining_hours > 1e-8:
            # Remove partial work for an infeasible item; plans are never partial.
            dynamic_items = [candidate for candidate in dynamic_items if candidate.key != item.key]
            continue

        assignments[item.key] = max(packet_date for packet_date, _ in item_chunks)
        item_chunks.sort(key=lambda value: (value[0], value[1]))
        if any(packet_date != item.local_date for packet_date, _ in item_chunks):
            placements.append(Placement(
                item_key=item.key,
                before_date=item.local_date,
                after_date=item_chunks[0][0],
                score=round(sum(candidate.score for candidate in item_candidates), 8),
                reason_codes=tuple(sorted({reason for candidate in item_candidates for reason in candidate.reason_codes})),
                effort_hours=item.estimated_hours,
                before_version=item.schedule_version,
                chunks=tuple(item_chunks),
            ))

    placements = list(bounded_local_improvement(snapshot, placements, selected_profile))
    final_keys = {placement.item_key for placement in placements}
    final_items = [item for item in snapshot.items if item.key not in final_keys]
    source_map = _work_units(snapshot.items)
    for placement in placements:
        source = source_map[placement.item_key]
        for packet_index, (packet_date, packet_hours) in enumerate(placement.chunks):
            final_items.append(replace(
                source,
                local_date=packet_date,
                estimated_hours=packet_hours,
                effort_source="plan",
                metadata={**source.metadata, "packet_index": packet_index},
            ))
    final_snapshot = ScheduleSnapshot(
        user_id=snapshot.user_id,
        items=tuple(final_items),
        dependencies=snapshot.dependencies,
        preferences=snapshot.preferences,
        capacity_overrides=snapshot.capacity_overrides,
        revision=snapshot.revision,
    )
    daily_loads, _ = analyze_dates(final_snapshot)
    return RebalanceResult(
        feasible=not blockers,
        profile=selected_profile.name,
        placements=tuple(placements),
        daily_loads=tuple(daily_loads),
        blockers=tuple(sorted(set(blockers))),
        capacity_deficit_hours=round(total_deficit_hours, 4),
        earliest_feasible_completion_date=earliest_completion,
        affected_items=tuple(sorted(set(affected_items))),
    )
