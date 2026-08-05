import logging
import os
import tempfile

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import (
    Base,
    SessionLocal,
    _try_acquire_file_lock,
    auto_sync_tables,
    engine,
    sync_reminder_legacy_foreign_keys,
    sync_reminder_user_foreign_keys,
)
from routers import auth, billing, calendar, chat, deadlines, reminders, scheduling, scheduling_personalization, tasks
import models  # noqa: F401 - register every ORM model before startup create_all
from services.image_storage import UPLOAD_DIR
from services.reminder_seeds import seed_builtin_role_cards
from services.schedule_policy import scheduling_enabled


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="长期任务规划师 - 输入目标和截止日期，自动生成分阶段执行计划，支持任何长期任务的拆解与进度管理",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Create/sync tables and seed role cards once across multiple workers."""
    lock_file = os.path.join(tempfile.gettempdir(), "ibuddy_startup.lock")
    with open(lock_file, "a+b") as file_obj:
        if not _try_acquire_file_lock(file_obj):
            logging.getLogger(__name__).info("[startup] another worker owns the startup lock; skipping")
            return

        Base.metadata.create_all(bind=engine)
        auto_sync_tables(engine, Base)
        sync_reminder_user_foreign_keys(engine)
        sync_reminder_legacy_foreign_keys(engine)
        with SessionLocal() as db:
            seed_builtin_role_cards(db)
    logging.getLogger(__name__).info(
        "Scheduling balancer runtime: enabled=%s agent_tools=%s",
        scheduling_enabled(),
        _scheduling_agent_tools_registered(),
    )

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(deadlines.router)
app.include_router(chat.router)
app.include_router(calendar.router)
app.include_router(billing.router)
app.include_router(reminders.router)
app.include_router(scheduling.router)
app.include_router(scheduling_personalization.router)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "capabilities": {
            "scheduling_balancer": scheduling_enabled(),
            "scheduling_agent_tools": _scheduling_agent_tools_registered(),
            "automatic_scheduling_default": False,
        },
    }


def _scheduling_agent_tools_registered() -> bool:
    required = {
        "preflight_create_calendar_item",
        "resolve_overload_intervention",
        "analyze_schedule",
        "create_schedule_plan",
        "apply_schedule_plan",
        "undo_schedule_plan",
        "replan_schedule",
        "get_schedule_log",
    }
    return required.issubset(chat.TOOL_DISPATCH)
