"""Task CRUD tools — agent 可调用的数据库操作函数

主任务 → `task` 表，子任务 → `sub_task` 表，通过 task_id 外键关联。
约定：修改 = 先删除旧记录，再创建新记录。
所有函数返回 dict/list，便于序列化为 JSON 喂回给 agent。
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import date as date_type
from sqlalchemy.orm import Session
from models.task_new import Task, Priority, TaskCategory, TaskStatus, TaskType
from models.sub_task import SubTask
from models.app_user import AppUser

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
    category: str = "",
    deadline: Optional[str] = None,
    priority: str = "medium",
    estimated_hours: float = 0,
    task_type: str = "todo",
    status: str = "todo",
    personal_deadline: Optional[str] = None,
) -> Dict[str, Any]:
    """创建任务。子任务应通过 create_subtask 写入 sub_task 表。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        title: 任务标题（必填）
        description: 详细描述
        subject: 学科/分类标签
        deadline: 截止日期，格式 YYYY-MM-DD
        priority: low | medium | high | urgent
        estimated_hours: 预估工时（小时）
        task_type: todo | process
        status: 任务状态
        personal_deadline: 个人截止时间

    Returns:
        包含新任务完整信息的 dict
    """
    # 桥接用户（旧 users 表 → 新 user 表）
    actual_uid = _ensure_user_exists(db, user_id)

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

    # 映射 LLM 传入的 status
    status_map = {"pending": TaskStatus.todo, "todo": TaskStatus.todo,
                  "in_progress": TaskStatus.in_progress, "done": TaskStatus.done,
                  "overdue": TaskStatus.overdue}
    try:
        task_status = status_map.get(status, TaskStatus(status))
    except ValueError:
        task_status = TaskStatus.todo

    try:
        normalized_category = TaskCategory(category).value if category else None
    except ValueError:
        return {"error": "category must be IA, EE, TOK, or CAS"}

    task = Task(
        user_id=actual_uid,
        id_name=title,
        task_type=kind,
        title=title,
        description=description,
        subject=subject,
        category=normalized_category,
        priority=pri,
        deadline=due,
        estimated_hours=estimated_hours,
        status=task_status,
    )
    db.add(task)

    db.commit()
    db.refresh(task)

    logger.info(f"Task created: id={task.id}, title={task.title}")
    return _task_to_dict(task)


def list_tasks(
    db: Session,
    user_id: int,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """查询用户的所有任务，包含全部字段信息。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        status: 按状态过滤（todo | in_progress | done | overdue），不传返回全部
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

    if category:
        try:
            q = q.filter(Task.category == TaskCategory(category).value)
        except ValueError:
            pass  # Preserve the existing behavior for invalid filters.

    tasks = (
        q.order_by(Task.deadline.asc(), Task.priority.desc())
        .limit(limit)
        .all()
    )

    return [_task_to_dict(t) for t in tasks]


def update_task(
    db: Session,
    user_id: int,
    task_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    subject: Optional[str] = None,
    category: Optional[str] = None,
    deadline: Optional[str] = None,
    priority: Optional[str] = None,
    estimated_hours: Optional[float] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a task that belongs to the current user."""
    actual_uid = _ensure_user_exists(db, user_id)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == actual_uid).first()
    if not task:
        return {"error": f"Task {task_id} does not exist or is not accessible"}

    if title is not None and title.strip():
        task.title = title.strip()
        task.id_name = title.strip()
    if description is not None:
        task.description = description
    if subject is not None:
        task.subject = subject
    if category is not None:
        try:
            normalized = TaskCategory(category).value if category else ""
        except ValueError:
            return {"error": "category must be IA, EE, TOK, or CAS"}
        task.category = normalized or None
    if deadline is not None:
        try:
            task.deadline = date_type.fromisoformat(deadline) if deadline else None
        except (ValueError, TypeError):
            return {"error": "deadline must use YYYY-MM-DD"}
    if priority is not None:
        if priority not in {"low", "medium", "high", "urgent"}:
            return {"error": "invalid priority"}
        task.priority = priority
    if estimated_hours is not None:
        task.estimated_hours = max(0, estimated_hours)
    if status is not None:
        mapped_status = {
            "pending": "todo",
            "todo": "todo",
            "in_progress": "in_progress",
            "done": "done",
            "overdue": "overdue",
        }.get(status)
        if not mapped_status:
            return {"error": "invalid task status"}
        task.status = mapped_status

    db.commit()
    db.refresh(task)
    return {"ok": True, **_task_to_dict(task)}


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

    deleted_title = task.title

    # 清理 sub_task 表中的关联子任务（FK ON DELETE CASCADE 会自动处理，显式操作做双重保证）
    db.query(SubTask).filter(
        SubTask.task_id == task.id,
    ).delete(synchronize_session=False)

    db.delete(task)
    db.commit()

    logger.info(f"Task deleted: id={task_id}, title={deleted_title}")
    return {"ok": True, "deleted_id": task_id, "deleted_title": deleted_title}


# ═══════════════════════════════════════════════════════════════
# 用户桥接（旧 users 表 ↔ 新 user 表，以 username 为桥梁）
# ═══════════════════════════════════════════════════════════════

def _ensure_user_exists(db: Session, user_id: int) -> int:
    """确保调用方传入的 user_id 在新 user 表中有对应记录。
    以 username 为桥梁在 users ↔ user 两表间同步，解决 FK 约束冲突。
    返回实际写入 task 表时使用的 user.id。
    注意：旧 users 表无 ORM 模型，通过原生 SQL 查询。
    """
    from sqlalchemy import text

    # 1) 如果 user_id 直接在新表存在，直接返回
    exists = db.query(AppUser).filter(AppUser.id == user_id).first()
    if exists:
        return user_id

    # 2) 尝试从旧 users 表查找同名用户
    old_row = db.execute(
        text("SELECT id, username, password_hash FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if not old_row:
        return user_id  # 无法桥接，原样返回

    old_id, username, pwd_hash = old_row

    # 3) 查新表是否有同名用户
    new_user = db.query(AppUser).filter(AppUser.username == username).first()
    if new_user:
        logger.info(f"Bridged user: users.id={old_id} -> user.id={new_user.id} (matched by username='{username}')")
        return new_user.id

    # 4) 不存在则在新表创建
    new_user = AppUser(
        username=username,
        password=pwd_hash or "",
    )
    db.add(new_user)
    db.flush()
    logger.info(f"Bridged user: users.id={old_id} -> new user.id={new_user.id} (created by username='{username}')")
    return new_user.id


# ═══════════════════════════════════════════════════════════════
# 子任务操作（基于 sub_task 表，通过 task_id 外键关联，3 个函数）
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
    """为指定任务创建子任务。写入 sub_task 表，通过 task_id 关联父任务。

    Args:
        db: 数据库会话
        user_id: 用户 ID（用于校验父任务归属）
        task_id: 所属父任务 ID
        name: 子任务名称（必填）
        description: 详细描述
        notice_time: 子任务截止/提醒日期，格式 YYYY-MM-DD
        level: 优先级 low | medium | high | urgent
        status: 状态 pending | in_progress | done

    Returns:
        包含新子任务完整信息的 dict，或 {"error": str}
    """
    # 桥接用户
    actual_uid = _ensure_user_exists(db, user_id)

    # 权限校验：确认父任务属于该用户
    owner_task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == actual_uid,
    ).first()
    if not owner_task:
        return {"error": f"任务 {task_id} 不存在或无权操作"}

    # 解析日期
    try:
        due = date_type.fromisoformat(notice_time) if notice_time else None
    except (ValueError, TypeError):
        due = None

    # 校验 level 合法值
    valid_levels = {"low", "medium", "high", "urgent"}
    if level not in valid_levels:
        level = "medium"

    # 校验 status，映射值（agent 传入 todo/in_progress，表用 pending/in_progress）
    status_map = {"todo": "pending", "pending": "pending", "in_progress": "in_progress", "done": "done"}
    mapped_status = status_map.get(status, "pending")

    subtask = SubTask(
        task_id=task_id,
        name=name,
        description=description,
        notice_time=due,
        level=level,
        status=mapped_status,
    )
    db.add(subtask)
    db.commit()
    db.refresh(subtask)

    logger.info(f"SubTask created: id={subtask.id}, name={subtask.name}, task_id={task_id}")
    return _subtask_to_dict(subtask)


def list_subtasks(
    db: Session,
    user_id: int,
    task_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """查询子任务列表。通过 JOIN task 表按用户过滤。

    Args:
        db: 数据库会话
        user_id: 用户 ID（JOIN task 表校验归属）
        task_id: 按父任务 ID 过滤。不传则返回该用户所有子任务
        status: 按状态过滤
        limit: 最大返回条数

    Returns:
        子任务列表，每个元素包含全部字段
    """
    actual_uid = _ensure_user_exists(db, user_id)

    q = db.query(SubTask).join(Task, SubTask.task_id == Task.id).filter(
        Task.user_id == actual_uid
    )

    if task_id is not None:
        q = q.filter(SubTask.task_id == task_id)

    if status:
        q = q.filter(SubTask.status == status)

    subtasks = (
        q.order_by(SubTask.notice_time.asc(), SubTask.level.desc())
        .limit(limit)
        .all()
    )

    return [_subtask_to_dict(st) for st in subtasks]


def update_subtask(
    db: Session,
    user_id: int,
    subtask_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    notice_time: Optional[str] = None,
    level: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a timeline milestone that belongs to the current user."""
    actual_uid = _ensure_user_exists(db, user_id)
    subtask = db.query(SubTask).join(Task, SubTask.task_id == Task.id).filter(
        SubTask.id == subtask_id,
        Task.user_id == actual_uid,
    ).first()
    if not subtask:
        return {"error": f"Subtask {subtask_id} does not exist or is not accessible"}

    if name is not None and name.strip():
        subtask.name = name.strip()
    if description is not None:
        subtask.description = description
    if notice_time is not None:
        try:
            subtask.notice_time = date_type.fromisoformat(notice_time) if notice_time else None
        except (ValueError, TypeError):
            return {"error": "notice_time must use YYYY-MM-DD"}
    if level is not None:
        if level not in {"low", "medium", "high", "urgent"}:
            return {"error": "invalid subtask priority"}
        subtask.level = level
    if status is not None:
        mapped_status = {"todo": "pending", "pending": "pending", "in_progress": "in_progress", "done": "done"}.get(status)
        if not mapped_status:
            return {"error": "invalid subtask status"}
        subtask.status = mapped_status

    db.commit()
    db.refresh(subtask)
    return {"ok": True, **_subtask_to_dict(subtask)}


def delete_subtask(
    db: Session,
    subtask_id: int,
    user_id: int,
) -> Dict[str, Any]:
    """删除子任务。通过 JOIN task 表校验用户权限。

    Args:
        db: 数据库会话
        subtask_id: 要删除的子任务 ID（sub_task 表的 id）
        user_id: 用户 ID

    Returns:
        操作结果 {"ok": True, "deleted_id": int} 或 {"error": str}
    """
    actual_uid = _ensure_user_exists(db, user_id)

    subtask = db.query(SubTask).join(Task, SubTask.task_id == Task.id).filter(
        SubTask.id == subtask_id,
        Task.user_id == actual_uid,
    ).first()
    if not subtask:
        return {"error": f"子任务 {subtask_id} 不存在或无权操作"}

    deleted_name = subtask.name
    db.delete(subtask)
    db.commit()

    logger.info(f"SubTask deleted: id={subtask_id}, name={deleted_name}")
    return {"ok": True, "deleted_id": subtask_id, "deleted_name": deleted_name}


# ═══════════════════════════════════════════════════════════════
# 工具函数：把 ORM 对象转为纯 dict（便于 JSON 序列化）
# ═══════════════════════════════════════════════════════════════

def _task_to_dict(t: Task) -> Dict[str, Any]:
    """Task ORM → dict（包含所有字段）"""
    return {
        "id": t.id,
        "user_id": t.user_id,
        "task_type": t.task_type.value if t.task_type else "todo",
        "title": t.title,
        "description": t.description,
        "subject": t.subject,
        "category": t.category,
        "priority": t.priority or "medium",
        "status": t.status or "todo",
        "deadline": (t.deadline.date().isoformat() if t.deadline else None),
        "estimated_hours": float(t.estimated_hours) if t.estimated_hours else 0,
        "progress": t.progress,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "update_time": t.update_time.isoformat() if t.update_time else None,
    }


def _subtask_to_dict(st: SubTask) -> Dict[str, Any]:
    """SubTask ORM → dict（包含所有字段）"""
    return {
        "id": st.id,
        "task_id": st.task_id,
        "name": st.name,
        "description": st.description,
        "notice_time": st.notice_time.isoformat() if st.notice_time else None,
        "level": st.level or "medium",
        "status": st.status or "pending",
        "notice_method": st.notice_method,
        "created_at": st.created_at.isoformat() if st.created_at else None,
        "updated_at": st.updated_at.isoformat() if st.updated_at else None,
    }
