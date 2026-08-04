from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime
from database import get_db
from models.app_user import AppUser as User
from models.task_new import Task as TaskModel, TaskCategory, TaskStatus, TaskType
from models.sub_task import SubTask as SubTaskModel
from schemas.task import (
    SubTaskCreate,
    SubTaskUpdate,
    TaskBreakdownRequest,
    TaskCreate,
    TaskPlanPhase,
    TaskPlanRequest,
    TaskPlanResponse,
    TaskResponse,
    TaskUpdate,
)
from services.auth import get_current_user
from services.ai_service import ai_service
from services.reminder_preferences import normalize_task_reminder_offsets_minutes

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _normalize_category(value):
    if value is None:
        return None
    try:
        return TaskCategory(value).value
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="category must be IA, EE, TOK, or CAS") from exc


def _build_task_tree(tasks: List[TaskModel]) -> List[TaskResponse]:
    """构建任务树 —— 纯平铺，子任务由 sub_task 表单独合并"""
    return [TaskResponse.model_validate(t) for t in tasks]


@router.get("", response_model=List[TaskResponse])
def list_tasks(
    status: str = None,
    category: Optional[TaskCategory] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(TaskModel).filter(TaskModel.user_id == current_user.id)
    if status:
        query = query.filter(TaskModel.status == status)
    if category:
        query = query.filter(TaskModel.category == _normalize_category(category))
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
            category=parent.category,
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
    if "reminder_offsets_minutes" in payload and payload["reminder_offsets_minutes"] is not None:
        try:
            payload["reminder_offsets_minutes"] = list(
                normalize_task_reminder_offsets_minutes(payload["reminder_offsets_minutes"])
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.get("category"):
        payload["category"] = _normalize_category(payload["category"])
    task = TaskModel(
        user_id=current_user.id,
        task_type=TaskType(data.task_type),
        **payload,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    from services.schedule_triggers import analyze_after_mutation
    analyze_after_mutation(db, current_user.id, "task_create")
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
            category=task.category,
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
    if "reminder_offsets_minutes" in update_data and update_data["reminder_offsets_minutes"] is not None:
        try:
            update_data["reminder_offsets_minutes"] = list(
                normalize_task_reminder_offsets_minutes(
                    update_data["reminder_offsets_minutes"]
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if update_data.get("category"):
        update_data["category"] = _normalize_category(update_data["category"])
    for key, value in update_data.items():
        setattr(task, key, value)
    task.schedule_version = int(task.schedule_version or 1) + 1

    db.commit()
    db.refresh(task)
    normalized_status = str(getattr(task.status, "value", task.status) or "").lower()
    if normalized_status in {"done", "complete", "completed"}:
        from services.schedule_lifecycle import record_schedule_outcome
        record_schedule_outcome(db, current_user.id, "task", task.id, normalized_status)
    from services.schedule_triggers import analyze_after_mutation
    analyze_after_mutation(db, current_user.id, "task_update")
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
    from services.schedule_triggers import analyze_after_mutation
    analyze_after_mutation(db, current_user.id, "task_delete")
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
            category=task.category,
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

    sub = SubTaskModel(
        task_id=data.task_id,
        name=data.name,
        description=data.description or "",
        notice_time=data.notice_time,
        level=data.level,
        status=data.status,
        estimated_hours=data.estimated_hours,
        earliest_start_date=data.earliest_start_date,
        hard_deadline_date=data.hard_deadline_date,
        energy_intensity=data.energy_intensity,
        effort_source=data.effort_source,
        is_schedule_locked=data.is_schedule_locked,
        schedule_kind=data.schedule_kind,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    from services.schedule_triggers import analyze_after_mutation
    analyze_after_mutation(db, current_user.id, "subtask_create")

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
    data: SubTaskUpdate,
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
    valid_levels = {"low", "medium", "high", "urgent"}
    valid_statuses = {"pending", "todo", "in_progress", "done"}

    if "name" in update_data and update_data["name"]:
        sub.name = update_data["name"]
    if "description" in update_data:
        sub.description = update_data["description"] or ""
    if "notice_time" in update_data:
        sub.notice_time = update_data["notice_time"]
    if "level" in update_data:
        if update_data["level"] not in valid_levels:
            raise HTTPException(status_code=400, detail="Invalid subtask priority")
        sub.level = update_data["level"]
    if "status" in update_data:
        if update_data["status"] not in valid_statuses:
            raise HTTPException(status_code=400, detail="Invalid subtask status")
        sub.status = "pending" if update_data["status"] == "todo" else update_data["status"]

    for key in (
        "estimated_hours", "earliest_start_date", "hard_deadline_date",
        "energy_intensity", "effort_source", "is_schedule_locked", "schedule_kind",
    ):
        if key in update_data:
            setattr(sub, key, update_data[key])
    sub.schedule_version = int(sub.schedule_version or 1) + 1

    db.commit()
    db.refresh(sub)
    if str(sub.status or "").lower() in {"done", "complete", "completed"}:
        from services.schedule_lifecycle import record_schedule_outcome
        record_schedule_outcome(db, current_user.id, "subtask", sub.id, str(sub.status).lower())
    from services.schedule_triggers import analyze_after_mutation
    analyze_after_mutation(db, current_user.id, "subtask_update")
    return {
        "ok": True,
        "id": sub.id,
        "task_id": sub.task_id,
        "name": sub.name,
        "description": sub.description or "",
        "notice_time": sub.notice_time.isoformat() if sub.notice_time else None,
        "level": sub.level,
        "status": sub.status,
    }


@router.delete("/sub-tasks/{subtask_id}")
def delete_sub_task(
    subtask_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除当前用户流程任务中的一个子任务。"""
    sub = db.query(SubTaskModel).join(
        TaskModel, SubTaskModel.task_id == TaskModel.id
    ).filter(
        SubTaskModel.id == subtask_id,
        TaskModel.user_id == current_user.id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="子任务不存在")

    db.delete(sub)
    db.commit()
    from services.schedule_triggers import analyze_after_mutation
    analyze_after_mutation(db, current_user.id, "subtask_delete")
    return {"ok": True, "deleted_id": subtask_id}
