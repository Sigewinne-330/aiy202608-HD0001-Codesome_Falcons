from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from routers import auth, tasks, deadlines, chat, calendar

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

# 注册路由
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(deadlines.router)
app.include_router(chat.router)
app.include_router(calendar.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
