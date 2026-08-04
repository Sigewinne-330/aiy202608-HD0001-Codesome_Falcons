"""Non-secret readiness check for the scheduling schema."""

from database import Base, engine
import models  # noqa: F401 - registers all models in Base.metadata


def main() -> int:
    required_tables = {
        "task",
        "sub_task",
        "deadlines",
        "scheduling_preferences",
        "schedule_capacity_overrides",
        "schedule_item_dependencies",
        "schedule_allocations",
        "schedule_interventions",
        "schedule_plans",
        "schedule_plan_items",
        "schedule_audit_events",
    }
    existing = set(engine.dialect.get_table_names(engine.connect()))
    missing = sorted(required_tables - existing)
    if missing:
        print({"ok": False, "missing_tables": missing})
        return 1
    print({"ok": True, "tables": sorted(required_tables)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
