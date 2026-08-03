from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import date, datetime
from database import get_db
from models.app_user import AppUser as User
from models.task_new import Task as TaskModel, TaskStatus, TaskType
from schemas.task import TaskCreate, TaskUpdate, TaskResponse, TaskBreakdownRequest, TaskPlanRequest, TaskPlanResponse, TaskPlanPhase
from services.auth import get_current_user
from services.ai_service import ai_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _build_task_tree(tasks: List[TaskModel]) -> List[TaskResponse]:
    """构建任务树结构"""
    task_map = {t.id: TaskResponse.model_validate(t) for t in tasks}
    roots = []
    for t in tasks:
        resp = task_map[t.id]
        if t.parent_id and t.parent_id in task_map:
            task_map[t.parent_id].subtasks.append(resp)
        else:
            roots.append(resp)
    for task in task_map.values():
        task.subtasks.sort(key=lambda item: (item.is_final, item.deadline or date.max))
    return roots


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

    # 构建任务树（基于 tasks 表的 parent_id 自引用）
    tree = _build_task_tree(tasks)

    return tree


@router.post("", response_model=TaskResponse)
def create_task(
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.task_type not in {TaskType.todo.value, TaskType.process.value}:
        raise HTTPException(status_code=400, detail="任务类型必须是 todo 或 process")

    parent = None
    if data.parent_id is not None:
        parent = db.query(TaskModel).filter(
            TaskModel.id == data.parent_id,
            TaskModel.user_id == current_user.id,
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="父任务不存在")
        if parent.task_type != TaskType.process:
            raise HTTPException(status_code=400, detail="待办事项不能添加子任务")
        if data.task_type == TaskType.process.value:
            raise HTTPException(status_code=400, detail="流程任务不能嵌套流程任务")

    payload = data.model_dump(exclude={"task_type"})
    task = TaskModel(
        user_id=current_user.id,
        task_type=TaskType.todo if parent else TaskType(data.task_type),
        is_final=False,
        **payload,
    )
    db.add(task)

    final_task = None
    if not parent and task.task_type == TaskType.process:
        db.flush()
        final_task = TaskModel(
            user_id=current_user.id,
            parent_id=task.id,
            task_type=TaskType.todo,
            is_final=True,
            title=task.title,
            description="流程任务最终节点",
            subject=task.subject,
            priority=task.priority,
            status=TaskStatus.todo,
            deadline=task.deadline,
            estimated_hours=0,
            progress=0,
        )
        db.add(final_task)

    db.commit()
    db.refresh(task)
    response = TaskResponse.model_validate(task)
    if final_task:
        db.refresh(final_task)
        response.subtasks.append(TaskResponse.model_validate(final_task))
    return response


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

    # 同时获取子任务
    all_tasks = db.query(TaskModel).filter(TaskModel.user_id == current_user.id).all()
    task_map = {t.id: t for t in all_tasks}

    resp = TaskResponse.model_validate(task)
    for t in all_tasks:
        if t.parent_id == task.id:
            resp.subtasks.append(TaskResponse.model_validate(t))
    resp.subtasks.sort(key=lambda item: (item.is_final, item.deadline or date.max))
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
    if task.is_final:
        protected_fields = {"title", "deadline", "subject", "priority"}
        if protected_fields.intersection(update_data):
            raise HTTPException(status_code=400, detail="最终节点的标题和时间由流程主任务统一管理")
    for key, value in update_data.items():
        setattr(task, key, value)

    # 流程主任务的最终节点始终与主任务同标题、同截止时间。
    if task.parent_id is None and task.task_type == TaskType.process:
        final_task = db.query(TaskModel).filter(
            TaskModel.parent_id == task.id,
            TaskModel.user_id == current_user.id,
            TaskModel.is_final.is_(True),
        ).first()
        if final_task:
            final_task.title = task.title
            final_task.deadline = task.deadline
            final_task.subject = task.subject
            final_task.priority = task.priority
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
    if task.is_final:
        raise HTTPException(status_code=400, detail="最终节点由流程任务自动维护，不能单独删除")
    if task.parent_id is None and task.task_type == TaskType.process:
        db.query(TaskModel).filter(
            TaskModel.parent_id == task.id,
            TaskModel.user_id == current_user.id,
        ).delete(synchronize_session=False)
    db.delete(task)
    db.commit()
    return {"ok": True, "cascaded_children": child_count}


@router.post("/breakdown", response_model=List[TaskResponse])
async def breakdown_task(
    data: TaskBreakdownRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 拆解大型任务"""
    task = db.query(TaskModel).filter(
        TaskModel.id == data.task_id, TaskModel.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.task_type != TaskType.process or task.parent_id is not None:
        raise HTTPException(status_code=400, detail="只有流程主任务可以拆解为子任务")

    subtasks_data = await ai_service.breakdown_task(
        title=task.title,
        description=task.description or "",
        subject=task.subject or "",
    )

    created = []
    for st in subtasks_data:
        subtask = TaskModel(
            user_id=current_user.id,
            parent_id=task.id,
            task_type=TaskType.todo,
            is_final=False,
            title=st["title"],
            description=st.get("description", ""),
            subject=task.subject,
            priority=st.get("priority", "medium"),
            estimated_hours=st.get("estimated_hours", 1),
        )
        db.add(subtask)
        db.flush()
        created.append(TaskResponse.model_validate(subtask))

    db.commit()
    return created


@router.post("/plan", response_model=TaskPlanResponse)
async def plan_task(
    data: TaskPlanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """任务时间线规划 - 输入目标和截止日期，生成分阶段执行计划"""
    phases_data = await ai_service.plan_task_timeline(
        title=data.title,
        word_count=data.word_count,
        deadline=data.deadline,
        description=data.description or "",
    )

    phases = [TaskPlanPhase(**p) for p in phases_data]

    # 自动创建对应的任务
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

        # 写入 tasks 表（保留原有逻辑）
        subtask = TaskModel(
            user_id=current_user.id,
            parent_id=parent_task.id,
            title=f"{p.phase}：{data.title}",
            description=f"{p.description}\n交付物：{p.deliverables}",
            priority=p.priority,
            deadline=phase_due,
            estimated_hours=p.estimated_hours,
        )
        db.add(subtask)

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
