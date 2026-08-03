"""Task CRUD tools — agent 可调用的数据库操作函数

所有操作基于 tasks 表，子任务通过 parent_id 字段实现。
约定：修改 = 先删除旧记录，再创建新记录。
所有函数返回 dict/list，便于序列化为 JSON 喂回给 agent。
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import date as date_type
from sqlalchemy.orm import Session
from models.task import Task, Priority, TaskStatus, TaskType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# tasks 表操作（3 个函数）
# ═══════════════════════════════════════════════════════════════

def create_task(
    db: Session,
    user_id: int,
    title: str,
    description: str = "",
    subject: str = "",
    deadline: Optional[str] = None,
    priority: str = "medium",
    estimated_hours: float = 0,
    parent_id: Optional[int] = None,
    task_type: str = "todo",
) -> Dict[str, Any]:
    """创建任务。可以是独立任务，也可以指定 parent_id 作为某个任务的子任务。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        title: 任务标题（必填）
        description: 详细描述
        subject: 学科/分类标签
        deadline: 截止日期，格式 YYYY-MM-DD
        priority: low | medium | high | urgent
        estimated_hours: 预估工时（小时）
        parent_id: 父任务 ID，创建子任务时传入

    Returns:
        包含新任务完整信息的 dict
    """
    try:
        due = date_type.fromisoformat(deadline) if deadline else None
    except (ValueError, TypeError):
        due = None

    try:
        pri = Priority(priority)
    except ValueError:
        pri = Priority.medium

    try:
        kind = TaskType(task_type)
    except ValueError:
        kind = TaskType.todo

    if parent_id is not None:
        parent = db.query(Task).filter(
            Task.id == parent_id,
            Task.user_id == user_id,
        ).first()
        if not parent:
            return {"error": f"父任务 {parent_id} 不存在或无权操作"}
        if parent.task_type != TaskType.process:
            return {"error": "待办事项不能添加子任务"}
        kind = TaskType.todo

    task = Task(
        user_id=user_id,
        parent_id=parent_id,
        task_type=kind,
        is_final=False,
        title=title,
        description=description,
        subject=subject,
        priority=pri,
        deadline=due,
        estimated_hours=estimated_hours,
        status=TaskStatus.todo,
    )
    db.add(task)

    if parent_id is None and kind == TaskType.process:
        db.flush()
        db.add(Task(
            user_id=user_id,
            parent_id=task.id,
            task_type=TaskType.todo,
            is_final=True,
            title=task.title,
            description="流程任务最终节点",
            subject=task.subject,
            priority=task.priority,
            deadline=task.deadline,
            status=TaskStatus.todo,
            estimated_hours=0,
            progress=0,
        ))

    db.commit()
    db.refresh(task)

    logger.info(f"Task created: id={task.id}, title={task.title}, parent_id={task.parent_id}")
    return _task_to_dict(task)


def list_tasks(
    db: Session,
    user_id: int,
    status: Optional[str] = None,
    parent_id: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """查询用户的所有任务，包含全部字段信息。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        status: 按状态过滤（todo | in_progress | done | overdue），不传返回全部
        parent_id: 按父任务过滤，传 None 只返回顶层任务（parent_id IS NULL），不传返回全部
        limit: 最大返回条数，默认 50

    Returns:
        任务列表，每个元素包含任务的全部字段
    """
    q = db.query(Task).filter(Task.user_id == user_id)

    if status:
        try:
            q = q.filter(Task.status == TaskStatus(status))
        except ValueError:
            pass  # 非法 status 值则忽略过滤

    if parent_id is not None:
        q = q.filter(Task.parent_id == parent_id)

    tasks = (
        q.order_by(Task.deadline.asc(), Task.priority.desc())
        .limit(limit)
        .all()
    )

    return [_task_to_dict(t) for t in tasks]


def delete_task(
    db: Session,
    task_id: int,
    user_id: int,
) -> Dict[str, Any]:
    """删除任务；流程主任务会同时删除其全部子任务。

    Args:
        db: 数据库会话
        task_id: 要删除的任务 ID
        user_id: 用户 ID（用于权限校验）

    Returns:
        操作结果 {"ok": True, "deleted_id": int} 或 {"error": str}
    """
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == user_id,
    ).first()
    if not task:
        return {"error": f"任务 {task_id} 不存在或无权操作"}
    if task.is_final:
        return {"error": "最终节点由流程任务自动维护，不能单独删除"}

    deleted_title = task.title
    if task.parent_id is None and task.task_type == TaskType.process:
        db.query(Task).filter(
            Task.parent_id == task.id,
            Task.user_id == user_id,
        ).delete(synchronize_session=False)
    db.delete(task)
    db.commit()

    logger.info(f"Task deleted: id={task_id}, title={deleted_title}")
    return {"ok": True, "deleted_id": task_id, "deleted_title": deleted_title}


# ═══════════════════════════════════════════════════════════════
# 子任务操作（基于 tasks 表 + parent_id，3 个函数）
# ═══════════════════════════════════════════════════════════════

def create_subtask(
    db: Session,
    user_id: int,
    task_id: int,
    name: str,
    description: str = "",
    notice_time: Optional[str] = None,
    level: str = "medium",
    status: str = "todo",
) -> Dict[str, Any]:
    """为指定任务创建子任务。实质：在 tasks 表中创建一条 parent_id = task_id 的记录。

    Args:
        db: 数据库会话
        user_id: 用户 ID（用于校验父任务归属）
        task_id: 所属父任务 ID
        name: 子任务名称（必填）
        description: 详细描述
        notice_time: 子任务截止日期，格式 YYYY-MM-DD，映射到 deadline 字段
        level: 优先级 low | medium | high | urgent
        status: 状态 todo | in_progress | done | overdue

    Returns:
        包含新子任务完整信息的 dict，或 {"error": str}
    """
    # 权限校验：确认父任务属于该用户
    owner_task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == user_id,
    ).first()
    if not owner_task:
        return {"error": f"任务 {task_id} 不存在或无权操作"}
    if owner_task.task_type != TaskType.process:
        return {"error": "待办事项不能添加子任务，请先创建流程任务"}

    # notice_time 映射到 deadline
    try:
        due = date_type.fromisoformat(notice_time) if notice_time else None
    except (ValueError, TypeError):
        due = None

    try:
        pri = Priority(level)
    except ValueError:
        pri = Priority.medium

    try:
        st = TaskStatus(status)
    except ValueError:
        st = TaskStatus.todo

    subtask = Task(
        user_id=user_id,
        parent_id=task_id,
        task_type=TaskType.todo,
        is_final=False,
        title=name,
        description=description,
        priority=pri,
        deadline=due,
        status=st,
    )
    db.add(subtask)
    db.commit()
    db.refresh(subtask)

    logger.info(f"SubTask created: id={subtask.id}, title={subtask.title}, parent_task={task_id}")
    return _task_to_dict(subtask)


def list_subtasks(
    db: Session,
    user_id: int,
    task_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """查询子任务列表。只查询有 parent_id 的任务记录。

    Args:
        db: 数据库会话
        user_id: 用户 ID（只返回该用户拥有的子任务）
        task_id: 按父任务 ID 过滤。不传则返回该用户所有子任务（parent_id IS NOT NULL）
        status: 按状态过滤
        limit: 最大返回条数

    Returns:
        子任务列表，每个元素包含全部字段
    """
    q = db.query(Task).filter(Task.user_id == user_id)

    if task_id is not None:
        q = q.filter(Task.parent_id == task_id)
    else:
        q = q.filter(Task.parent_id.isnot(None))

    if status:
        try:
            q = q.filter(Task.status == TaskStatus(status))
        except ValueError:
            pass

    subtasks = (
        q.order_by(Task.deadline.asc(), Task.priority.desc())
        .limit(limit)
        .all()
    )

    return [_task_to_dict(st) for st in subtasks]


def delete_subtask(
    db: Session,
    subtask_id: int,
    user_id: int,
) -> Dict[str, Any]:
    """删除子任务。实质：删除 tasks 表中一条有 parent_id 的记录。

    Args:
        db: 数据库会话
        subtask_id: 要删除的子任务 ID（即 tasks 表的 id）
        user_id: 用户 ID

    Returns:
        操作结果 {"ok": True, "deleted_id": int} 或 {"error": str}
    """
    subtask = db.query(Task).filter(
        Task.id == subtask_id,
        Task.user_id == user_id,
        Task.parent_id.isnot(None),  # 确保是子任务而非顶层任务
    ).first()
    if not subtask:
        return {"error": f"子任务 {subtask_id} 不存在或无权操作（可能不是子任务）"}
    if subtask.is_final:
        return {"error": "最终节点由流程任务自动维护，不能单独删除"}

    deleted_title = subtask.title
    db.delete(subtask)
    db.commit()

    logger.info(f"SubTask deleted: id={subtask_id}, title={deleted_title}")
    return {"ok": True, "deleted_id": subtask_id, "deleted_title": deleted_title}


# ═══════════════════════════════════════════════════════════════
# 工具函数：把 ORM 对象转为纯 dict（便于 JSON 序列化）
# ═══════════════════════════════════════════════════════════════

def _task_to_dict(t: Task) -> Dict[str, Any]:
    """Task ORM → dict（包含所有字段）"""
    return {
        "id": t.id,
        "user_id": t.user_id,
        "parent_id": t.parent_id,
        "task_type": t.task_type.value if t.task_type else "todo",
        "is_final": bool(t.is_final),
        "title": t.title,
        "description": t.description,
        "subject": t.subject,
        "priority": t.priority.value if t.priority else "medium",
        "status": t.status.value if t.status else "todo",
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "estimated_hours": float(t.estimated_hours) if t.estimated_hours else 0,
        "progress": t.progress,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }
