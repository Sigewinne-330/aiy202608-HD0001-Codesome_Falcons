from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, timedelta
from calendar import monthrange
from pydantic import BaseModel
from database import get_db
from models.user import User
from models.task import Task as TaskModel, TaskStatus
from models.deadline import Deadline as DeadlineModel, DeadlineStatus
from services.auth import get_current_user

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class CalendarDayItem(BaseModel):
    """日历中某一天的任务/截止日期条目"""
    id: int
    title: str
    type: str  # "task" or "deadline"
    priority: str
    status: str
    subject: Optional[str] = None

    class Config:
        from_attributes = True


class CalendarDayData(BaseModel):
    """某一天的汇总数据"""
    date: str
    tasks: List[CalendarDayItem] = []
    deadlines: List[CalendarDayItem] = []
    count: int = 0  # 总条数


class CalendarMonthResponse(BaseModel):
    """月度日历数据响应"""
    year: int
    month: int
    days: List[CalendarDayData] = []


@router.get("", response_model=CalendarMonthResponse)
def get_calendar_data(
    year: int = Query(default=None),
    month: int = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取指定月份的日历数据（任务 + 截止日期，按天分组）"""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    # 计算该月的第一天和最后一天
    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day = date(year, month, last_day_num)

    # 扩展范围：包含上月末尾和下月开头，用于填充日历格子
    # 确保我们能获取到日历网格中所有日期的数据
    start_date = first_day - timedelta(days=first_day.weekday())  # 扩展到周日
    end_date = last_day + timedelta(days=(6 - last_day.weekday()))  # 扩展到周六

    # 查询该时间段内的所有任务（仅父任务，子任务从 sub_tasks 表读取避免重复）
    tasks = db.query(TaskModel).filter(
        TaskModel.user_id == current_user.id,
        TaskModel.parent_id == None,
        TaskModel.deadline >= start_date,
        TaskModel.deadline <= end_date,
    ).order_by(TaskModel.deadline.asc(), TaskModel.priority.desc()).all()

    # 查询该时间段内的所有截止日期
    deadlines = db.query(DeadlineModel).filter(
        DeadlineModel.user_id == current_user.id,
        DeadlineModel.due_date >= start_date,
        DeadlineModel.due_date <= end_date,
    ).order_by(DeadlineModel.due_date.asc(), DeadlineModel.priority.desc()).all()

    # 查询该时间段内的所有子任务（tasks 表中 parent_id IS NOT NULL 的记录）
    sub_tasks = db.query(TaskModel).filter(
        TaskModel.user_id == current_user.id,
        TaskModel.parent_id.isnot(None),
        TaskModel.deadline >= start_date,
        TaskModel.deadline <= end_date,
    ).order_by(TaskModel.deadline.asc(), TaskModel.priority.desc()).all()

    # 按日期分组
    from collections import defaultdict
    day_map: dict[str, dict] = defaultdict(lambda: {"tasks": [], "deadlines": [], "count": 0})

    for t in tasks:
        if t.deadline:
            date_key = t.deadline.isoformat()
            item = CalendarDayItem(
                id=t.id,
                title=t.title,
                type="task",
                priority=t.priority.value if t.priority else "medium",
                status=t.status.value if t.status else "todo",
                subject=t.subject,
            )
            day_map[date_key]["tasks"].append(item)
            day_map[date_key]["count"] += 1

    for d in deadlines:
        date_key = d.due_date.isoformat()
        item = CalendarDayItem(
            id=d.id,
            title=d.title,
            type="deadline",
            priority=d.priority.value if d.priority else "medium",
            status=d.status.value if d.status else "pending",
            subject=d.subject,
        )
        day_map[date_key]["deadlines"].append(item)
        day_map[date_key]["count"] += 1

    for st in sub_tasks:
        if st.deadline:
            date_key = st.deadline.isoformat()
            item = CalendarDayItem(
                id=st.id,
                title=st.title,
                type="task",
                priority=st.priority.value if st.priority else "medium",
                status=st.status.value if st.status else "todo",
                subject=st.subject,
            )
            day_map[date_key]["tasks"].append(item)
            day_map[date_key]["count"] += 1

    # 构建响应（按日期排序）
    days = []
    current = start_date
    while current <= end_date:
        date_key = current.isoformat()
        data = day_map.get(date_key, {"tasks": [], "deadlines": [], "count": 0})
        days.append(CalendarDayData(
            date=date_key,
            tasks=data["tasks"],
            deadlines=data["deadlines"],
            count=data["count"],
        ))
        current += timedelta(days=1)

    return CalendarMonthResponse(year=year, month=month, days=days)
