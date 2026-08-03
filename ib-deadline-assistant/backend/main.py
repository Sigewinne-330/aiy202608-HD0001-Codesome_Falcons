import logging
import os
import tempfile

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import Base, SessionLocal, _try_acquire_file_lock, auto_sync_tables, engine
from routers import auth, billing, calendar, chat, deadlines, reminders, tasks
from services.image_storage import UPLOAD_DIR
from services.reminder_seeds import seed_builtin_role_cards


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
        with SessionLocal() as db:
            seed_builtin_role_cards(db)


app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(deadlines.router)
app.include_router(chat.router)
app.include_router(calendar.router)
app.include_router(billing.router)
app.include_router(reminders.router)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
