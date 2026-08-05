"""Non-mutating runtime gate for the user-workload scheduling balancer."""

from __future__ import annotations

import argparse
import json
from datetime import date

from database import SessionLocal
from models.app_user import AppUser
from models.deadline import Deadline
from models.scheduling import ScheduleAllocation, ScheduleIntervention
from models.sub_task import SubTask
from models.task_new import Task
from routers import chat
from schemas.scheduling import PreflightRequest
from services.schedule_engine import analyze_dates
from services.schedule_lifecycle import preflight_creation
from services.schedule_policy import scheduling_enabled
from services.schedule_projection import load_snapshot
from services.scheduling_tools_schema import SCHEDULING_TOOLS


def _counts(db, user_id: int) -> dict[str, int]:
    return {
        "tasks": db.query(Task).filter_by(user_id=user_id).count(),
        "subtasks": (
            db.query(SubTask)
            .join(Task, SubTask.task_id == Task.id)
            .filter(Task.user_id == user_id)
            .count()
        ),
        "deadlines": db.query(Deadline).filter_by(user_id=user_id).count(),
        "allocations": db.query(ScheduleAllocation).filter_by(user_id=user_id).count(),
        "interventions": db.query(ScheduleIntervention).filter_by(user_id=user_id).count(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--date", dest="target_date")
    args = parser.parse_args()

    required_tools = {tool["function"]["name"] for tool in SCHEDULING_TOOLS}
    registered_tools = {tool["function"]["name"] for tool in chat.ALL_TOOLS}
    missing_tools = sorted(required_tools - registered_tools)
    if not scheduling_enabled() or missing_tools:
        print(json.dumps({
            "ok": False,
            "code": "scheduling_runtime_disabled",
            "enabled": scheduling_enabled(),
            "missing_tools": missing_tools,
        }))
        return 1

    with SessionLocal() as db:
        user = db.query(AppUser).filter(AppUser.username == args.username).first()
        if not user:
            print(json.dumps({"ok": False, "code": "user_not_found"}))
            return 2

        snapshot = load_snapshot(db, user.id)
        rows, _ = analyze_dates(snapshot)
        if args.target_date:
            target = date.fromisoformat(args.target_date)
            row = next((item for item in rows if item["date"] == target.isoformat()), None)
        else:
            row = next((item for item in rows if item.get("item_count", 0) >= 3), None)
            target = date.fromisoformat(row["date"]) if row else None
        if not row or target is None:
            print(json.dumps({"ok": False, "code": "no_acceptance_date_with_three_items"}))
            return 3

        before = _counts(db, user.id)
        result = preflight_creation(
            db,
            user.id,
            PreflightRequest(
                source_type="task",
                title="runtime acceptance candidate",
                description="bounded one-hour acceptance item",
                target_date=target,
                estimated_hours=1,
                priority="medium",
            ),
            persist_intervention=False,
        )
        after = _counts(db, user.id)
        expected_overload = int(row["item_count"]) >= 3
        ok = (
            before == after
            and (not expected_overload or result.get("kind") == "overload_intervention")
        )
        print(json.dumps({
            "ok": ok,
            "enabled": True,
            "registered_scheduling_tools": len(required_tools),
            "target_date": target.isoformat(),
            "existing_count": row["item_count"],
            "preflight_kind": result.get("kind"),
            "projected_count": result.get("projected_count"),
            "recommended_date": (result.get("recommendation") or {}).get("date"),
            "side_effect_free": before == after,
        }))
        return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
