import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from routers import auth, tasks, deadlines, chat, calendar
from database import engine, Base, auto_sync_tables

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
    """每次启动自动建表 + 同步列（只增不改不删）"""
    Base.metadata.create_all(bind=engine)
    auto_sync_tables(engine, Base)

# 注册路由
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(deadlines.router)
app.include_router(chat.router)
app.include_router(calendar.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
