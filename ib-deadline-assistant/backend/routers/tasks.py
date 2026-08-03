from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
from database import get_db
from models.app_user import AppUser as User
from models.task_new import Task as TaskModel, TaskStatus, TaskType
from models.sub_task import SubTask as SubTaskModel
from schemas.task import TaskCreate, TaskUpdate, TaskResponse, TaskBreakdownRequest, TaskPlanRequest, TaskPlanResponse, TaskPlanPhase
from services.auth import get_current_user
from services.ai_service import ai_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _build_task_tree(tasks: List[TaskModel]) -> List[TaskResponse]:
    """构建任务树 —— 纯平铺，子任务由 sub_task 表单独合并"""
    return [TaskResponse.model_validate(t) for t in tasks]


@router.get("", response_model=List[TaskResponse])
def list_tasks(
    status: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(TaskModel).filter(TaskModel.user_id == current_user.id)
    if status:
        query = query.filter(TaskModel.status == status)
    tasks = query.order_by(TaskModel.deadline.asc(), TaskModel.priority.desc()).all()

    # 构建任务树（平铺的顶层任务）
    tree = _build_task_tree(tasks)

    # 从 sub_task 表查询子任务，合并到对应的流程任务中
    sub_tasks = db.query(SubTaskModel).join(
        TaskModel, SubTaskModel.task_id == TaskModel.id
    ).filter(
        TaskModel.user_id == current_user.id
    ).order_by(SubTaskModel.notice_time.asc()).all()

    # 建立 task_id → TaskResponse 的索引
    if sub_tasks:
        id_to_response = {t.id: t for t in tree}

    for st in sub_tasks:
        parent = id_to_response.get(st.task_id)
        if parent is None:
            continue
        mapped = TaskResponse(
            id=st.id,
            user_id=current_user.id,
            task_type="todo",
            title=st.name,
            description=st.description or "",
            subject=parent.subject,
            priority=st.level or "medium",
            status=st.status or "pending",
            deadline=st.notice_time,
            estimated_hours=0,
            progress=0,
            created_at=st.created_at or datetime.now(),
            update_time=st.updated_at,
        )
        mapped.sub_task_source = True  # type: ignore[attr-defined]
        parent.subtasks.append(mapped)

    # 动态判断 task_type：任何有 sub_task 子任务的任务自动变为 process
    _process_ids = {st.task_id for st in sub_tasks}
    for root in tree:
        if root.id in _process_ids:
            root.task_type = "process"

    return tree


@router.post("", response_model=TaskResponse)
def create_task(
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.task_type not in {TaskType.todo.value, TaskType.process.value}:
        raise HTTPException(status_code=400, detail="任务类型必须是 todo 或 process")

    payload = data.model_dump(exclude={"task_type"})
    task = TaskModel(
        user_id=current_user.id,
        task_type=TaskType(data.task_type),
        **payload,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return TaskResponse.model_validate(task)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(TaskModel).filter(
        TaskModel.id == task_id, TaskModel.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    resp = TaskResponse.model_validate(task)

    # 从 sub_task 表获取子任务
    sub_tasks = db.query(SubTaskModel).filter(
        SubTaskModel.task_id == task.id
    ).order_by(SubTaskModel.notice_time.asc()).all()

    for st in sub_tasks:
        mapped = TaskResponse(
            id=st.id,
            user_id=current_user.id,
            task_type="todo",
            title=st.name,
            description=st.description or "",
            subject=task.subject,
            priority=st.level or "medium",
            status=st.status or "pending",
            deadline=st.notice_time,
            estimated_hours=0,
            progress=0,
            created_at=st.created_at or datetime.now(),
            update_time=st.updated_at,
        )
        mapped.sub_task_source = True  # type: ignore[attr-defined]
        resp.subtasks.append(mapped)

    return resp


@router.put("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(TaskModel).filter(
        TaskModel.id == task_id, TaskModel.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task, key, value)

    db.commit()
    db.refresh(task)
    return TaskResponse.model_validate(task)


@router.delete("/{task_id}")
def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(TaskModel).filter(
        TaskModel.id == task_id, TaskModel.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # sub_task 表 FK 设置了 ON DELETE CASCADE，数据库自动级联删除
    db.delete(task)
    db.commit()
    return {"ok": True}


@router.post("/breakdown", response_model=List[TaskResponse])
async def breakdown_task(
    data: TaskBreakdownRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 拆解大型任务 —— 子任务写入 sub_task 表"""
    task = db.query(TaskModel).filter(
        TaskModel.id == data.task_id, TaskModel.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    subtasks_data = await ai_service.breakdown_task(
        title=task.title,
        description=task.description or "",
        subject=task.subject or "",
    )

    created = []
    for st in subtasks_data:
        sub = SubTaskModel(
            task_id=task.id,
            name=st["title"],
            description=st.get("description", ""),
            level=st.get("priority", "medium"),
            status="pending",
        )
        db.add(sub)
        db.flush()
        created.append(TaskResponse(
            id=sub.id,
            user_id=current_user.id,
            task_type="todo",
            title=sub.name,
            description=sub.description or "",
            subject=task.subject,
            priority=sub.level or "medium",
            status=sub.status,
            deadline=None,
            estimated_hours=0,
            progress=0,
            created_at=sub.created_at or datetime.now(),
            update_time=sub.updated_at,
        ))

    db.commit()
    return created


@router.post("/plan", response_model=TaskPlanResponse)
async def plan_task(
    data: TaskPlanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """任务时间线规划 —— 子任务写入 sub_task 表"""
    phases_data = await ai_service.plan_task_timeline(
        title=data.title,
        word_count=data.word_count,
        deadline=data.deadline,
        description=data.description or "",
    )

    phases = [TaskPlanPhase(**p) for p in phases_data]

    try:
        due_date = date.fromisoformat(data.deadline) if data.deadline else None
    except ValueError:
        due_date = None

    parent_task = TaskModel(
        user_id=current_user.id,
        task_type=TaskType.process,
        title=data.title,
        description=f"任务规模：{data.word_count}\n{data.description or ''}",
        priority="urgent",
        deadline=due_date,
        estimated_hours=sum(p.estimated_hours for p in phases),
    )
    db.add(parent_task)
    db.flush()

    for p in phases:
        try:
            phase_due = date.fromisoformat(p.end_date)
        except ValueError:
            phase_due = None

        sub = SubTaskModel(
            task_id=parent_task.id,
            name=f"{p.phase}：{data.title}",
            description=f"{p.description}\n交付物：{p.deliverables}",
            notice_time=phase_due,
            level=p.priority,
            status="pending",
        )
        db.add(sub)

    db.commit()

    total_hours = sum(p.estimated_hours for p in phases)
    try:
        total_days = (date.fromisoformat(data.deadline) - date.today()).days if data.deadline else 30
    except ValueError:
        total_days = 30

    return TaskPlanResponse(
        title=data.title,
        word_count=data.word_count,
        deadline=data.deadline,
        phases=phases,
        total_hours=total_hours,
        total_days=total_days,
    )


# ── sub_task 表操作 ────────────────────────────────────────────

from pydantic import BaseModel as PydanticBase

class SubTaskCreate(PydanticBase):
    task_id: int
    name: str
    description: Optional[str] = ""
    notice_time: Optional[str] = None  # YYYY-MM-DD
    level: str = "medium"
    status: str = "pending"


@router.post("/sub-tasks")
def create_sub_task(
    data: SubTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """在 sub_task 表中创建子任务（供前端调用）"""
    parent = db.query(TaskModel).filter(
        TaskModel.id == data.task_id,
        TaskModel.user_id == current_user.id,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="父任务不存在")

    try:
        notice = date.fromisoformat(data.notice_time) if data.notice_time else None
    except (ValueError, TypeError):
        notice = None

    sub = SubTaskModel(
        task_id=data.task_id,
        name=data.name,
        description=data.description or "",
        notice_time=notice,
        level=data.level,
        status=data.status,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    return {
        "ok": True,
        "id": sub.id,
        "task_id": sub.task_id,
        "name": sub.name,
        "notice_time": sub.notice_time.isoformat() if sub.notice_time else None,
        "level": sub.level,
        "status": sub.status,
    }


@router.put("/sub-tasks/{subtask_id}")
def update_sub_task(
    subtask_id: int,
    data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新 sub_task 表中子任务的状态/进度（供前端 toggle 调用）"""
    sub = db.query(SubTaskModel).join(
        TaskModel, SubTaskModel.task_id == TaskModel.id
    ).filter(
        SubTaskModel.id == subtask_id,
        TaskModel.user_id == current_user.id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="子任务不存在")

    update_data = data.model_dump(exclude_unset=True)
    if "status" in update_data:
        sub.status = update_data["status"]
    if "progress" in update_data and hasattr(sub, "progress"):
        sub.progress = update_data["progress"]

    db.commit()
    return {"ok": True, "id": subtask_id, "status": sub.status}
