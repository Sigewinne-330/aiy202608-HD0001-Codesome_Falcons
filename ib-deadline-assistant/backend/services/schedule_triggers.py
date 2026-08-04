"""Mutation and daily-analysis hooks for the backend-first scheduler."""

from datetime import timedelta
from typing import Callable, Optional

from sqlalchemy.orm import Session

from models.app_user import AppUser
from services.schedule_engine import analyze_dates
from services.schedule_lifecycle import _audit
from services.schedule_lifecycle import apply_plan, create_plan
from schemas.scheduling import PlanApplyRequest, PlanCreateRequest
from services.schedule_policy import scheduling_enabled
from services.schedule_projection import load_snapshot


PostCommitAdapter = Callable[[Session, int, int, dict], None]


def create_internal_schedule_notification(
    db: Session,
    user_id: int,
    plan_id: int,
    summary: dict,
) -> None:
    """Create a user-visible scheduling-history notification after apply.

    Scheduling history is the backend-first notification surface.  A future
    frontend can render this event in the AI drawer without changing the
    transaction that applied the plan.
    """
    _audit(
        db,
        user_id,
        "schedule_internal_notification",
        actor="system",
        plan_id=plan_id,
        reason_codes=["automatic_schedule_applied"],
        metadata={
            "notification_kind": "automatic_schedule_applied",
            "affected_count": int(summary.get("affected_count", 0)),
        },
    )
    db.commit()


def analyze_after_mutation(
    db: Session,
    user_id: int,
    trigger: str,
    *,
    notification_adapter: Optional[PostCommitAdapter] = None,
    email_adapter: Optional[PostCommitAdapter] = None,
) -> dict:
    """Create a sanitized signal; never moves data when auto-scheduling is off."""
    if not scheduling_enabled():
        return {"enabled": False, "trigger": trigger, "mutated": False}
    snapshot = load_snapshot(db, user_id)
    rows, blockers = analyze_dates(
        snapshot,
        start_date=snapshot.local_today,
        end_date=snapshot.local_today + timedelta(days=snapshot.preferences.no_deadline_horizon_days),
    )
    overloaded = [row for row in rows if row.get("overloaded")]
    auto_applied = False
    auto_plan_id = None
    post_commit_errors = []
    if overloaded and snapshot.preferences.auto_scheduling_enabled:
        # Auto mode uses the same preview/apply transaction and a deterministic
        # idempotency key.  Hard/locked/completed records are filtered by the
        # engine and remain untouched.
        preview = create_plan(
            db,
            user_id,
            PlanCreateRequest(
                profile="balanced",
                idempotency_key=f"auto-{snapshot.revision[:48]}",
            ),
        )
        auto_plan_id = preview.get("id")
        if preview.get("feasible") and preview.get("item_changes"):
            applied = apply_plan(
                db,
                user_id,
                auto_plan_id,
                PlanApplyRequest(
                    expected_input_revision=preview["input_revision"],
                    idempotency_key=f"auto-apply-{snapshot.revision[:48]}",
                ),
                actor="system",
            )
            auto_applied = applied.get("state") == "applied"
            if auto_applied:
                summary = {"affected_count": len(applied.get("item_changes", []))}
                adapter = notification_adapter or create_internal_schedule_notification
                try:
                    adapter(db, user_id, auto_plan_id, summary)
                except Exception:
                    # The plan was committed by apply_plan already.  Notification
                    # failures are isolated in a fresh transaction and cannot
                    # roll back or duplicate schedule mutations.
                    db.rollback()
                    post_commit_errors.append("internal_notification_failed")
                if email_adapter is not None:
                    try:
                        email_adapter(db, user_id, auto_plan_id, summary)
                    except Exception:
                        db.rollback()
                        post_commit_errors.append("high_impact_email_failed")
    if overloaded:
        _audit(
            db,
            user_id,
            "analysis_signal",
            actor="system",
            reason_codes=["overload_after_reserve"],
            metadata={"trigger": trigger, "overloaded_dates": [row["date"] for row in overloaded[:30]]},
        )
        db.commit()
    return {
        "enabled": True,
        "trigger": trigger,
        "mutated": auto_applied,
        "auto_plan_id": auto_plan_id,
        "auto_applied": auto_applied,
        "overloaded_dates": [row["date"] for row in overloaded],
        "blockers": blockers,
        "post_commit_errors": post_commit_errors,
    }


def run_daily_schedule_analysis(db: Session) -> dict:
    """Worker-callable daily hook; refreshes signals without implicit movement."""
    if not scheduling_enabled():
        return {"enabled": False, "users": 0, "signals": 0}
    users = db.query(AppUser.id).all()
    signals = 0
    for (user_id,) in users:
        result = analyze_after_mutation(db, user_id, "daily_analysis")
        signals += len(result.get("overloaded_dates", []))
    return {"enabled": True, "users": len(users), "signals": signals}
