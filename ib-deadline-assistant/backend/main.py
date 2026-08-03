import logging
import fcntl
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import settings
from routers import auth, tasks, deadlines, chat, calendar, billing
from database import engine, Base, auto_sync_tables
from services.image_storage import UPLOAD_DIR

# 配置日志输出到控制台（INFO 级别，用于调试 LLM 返回）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="长期任务规划师 - 输入目标和截止日期，自动生成分阶段执行计划，支持任何长期任务的拆解与进度管理",
)

# CORS - 允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """每次启动自动建表 + 同步列（文件锁保证单 worker 执行）"""
    lock_file = "/tmp/auto_sync.lock"
    with open(lock_file, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.getLogger(__name__).info("[startup] 已被其他 worker 执行，跳过")
            return
        Base.metadata.create_all(bind=engine)
        auto_sync_tables(engine, Base)

# 注册路由
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(deadlines.router)
app.include_router(chat.router)
app.include_router(calendar.router)
app.include_router(billing.router)

# 静态资源：上传的图片（chat_message.extra 只存 /uploads/... URL，图片文件落盘于此）
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
