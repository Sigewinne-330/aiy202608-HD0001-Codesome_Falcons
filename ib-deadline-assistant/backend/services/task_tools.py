"""Task CRUD tools — agent 可调用的数据库操作函数

所有操作基于 task 表（主任务）和 sub_task 表（子任务），通过 task_id 外键关联。
约定：修改 = 先删除旧记录，再创建新记录。
所有函数返回 dict/list，便于序列化为 JSON 喂回给 agent。

user_id 桥接说明：
  - task / sub_task 表的 user_id 外键指向 `user` 表（新架构）
  - 但鉴权系统使用 `users` 表（旧架构），传入的 user_id 是 `users.id`
  - _ensure_user_exists() 负责同步：按 username 在 `user` 表查找/创建对应记录
  - 所有写操作（create_task / create_subtask）返回前会调用此桥接
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import date as date_type, datetime
from sqlalchemy.orm import Session
from models.task import Task, Priority, TaskStatus, TaskType
from models.user import User
from models.app_user import AppUser
from models.task_new import Task as AppTask
from models.sub_task import SubTask

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# user_id 桥接：users 表 → user 表
# ═══════════════════════════════════════════════════════════════

def _ensure_user_exists(db: Session, legacy_user_id: int) -> int:
    """确保 `user` 表中存在与 `users` 表对应的用户记录，返回 `user.id`。

    task 表的 FK 指向 `user`（新表），但鉴权传入的 user_id 来自 `users`（旧表）。
    此函数以 username 为桥梁在两张表之间同步，首次写入时自动创建。
    """
    # 1. 先尝试直接在 user 表按 id 查找（最常见路径，零开销）
    if db.query(AppUser).filter(AppUser.id == legacy_user_id).first():
        return legacy_user_id

    # 2. 从 users 表获取该用户的 username
    legacy_user = db.query(User).filter(User.id == legacy_user_id).first()
    if not legacy_user:
        logger.warning(f"Cannot bridge user_id={legacy_user_id}: not found in `users` table")
        return legacy_user_id  # 兜底：原样返回，让 FK 报错以便排查

    # 3. 在 user 表按 username 查找（可能 id 不同但同一人）
    app_user = db.query(AppUser).filter(
        AppUser.username == legacy_user.username
    ).first()
    if app_user:
        logger.info(
            f"Bridged user: users.id={legacy_user_id} -> user.id={app_user.id} "
            f"(matched by username={legacy_user.username!r})"
        )
        return app_user.id

    # 4. 不存在 → 在 user 表中创建对应记录
    app_user = AppUser(
        username=legacy_user.username,
        nickname=legacy_user.username,
        password="",  # auth 走 users 表，此处仅为满足 NOT NULL 约束
        email=legacy_user.email,
    )
    db.add(app_user)
    db.flush()  # 获取自增 id，不提交（由外层统一 commit）
    logger.info(
        f"Auto-created user in `user` table: id={app_user.id}, "
        f"username={app_user.username!r} (bridged from users.id={legacy_user_id})"
    )
    return app_user.id


# ═══════════════════════════════════════════════════════════════
# task 表操作（3 个函数）
# ═══════════════════════════════════════════════════════════════

def create_task(
    db: Session,
    user_id: int,
    title: str,
    description: str = "",
    deadline: Optional[str] = None,
<<<<<<< HEAD
    priority: str = "medium",
    estimated_hours: float = 0,
    parent_id: Optional[int] = None,
    task_type: str = "todo",
=======
    status: str = "pending",
    personal_deadline: Optional[str] = None,
    **kwargs,
>>>>>>> 081b93a (function call数据表调用问题修复)
) -> Dict[str, Any]:
    """创建任务。新架构中 task 表不再支持 parent_id，子任务统一使用 sub_task 表。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        title: 任务标题（必填），映射到 id_name 字段
        description: 详细描述
        deadline: 截止日期，格式 YYYY-MM-DD 或 ISO datetime
        status: 任务状态，默认 "pending"
        personal_deadline: 个人截止时间，格式 YYYY-MM-DD 或 ISO datetime
        **kwargs: 兼容旧参数（parent_id, subject, priority, estimated_hours），会被静默忽略

    Returns:
        包含新任务完整信息的 dict
    """
    # user_id 桥接：确保 user 表中存在对应记录（FK 指向 user 表）
    bridged_user_id = _ensure_user_exists(db, user_id)

    # 解析 deadline（兼容 date 和 datetime 格式）
    try:
        due = datetime.fromisoformat(deadline) if deadline else None
    except (ValueError, TypeError):
        try:
            due = datetime.combine(date_type.fromisoformat(deadline), datetime.min.time()) if deadline else None
        except (ValueError, TypeError):
            due = None

    # 解析 personal_deadline
    try:
        pd_dt = datetime.fromisoformat(personal_deadline) if personal_deadline else None
    except (ValueError, TypeError):
        try:
            pd_dt = datetime.combine(date_type.fromisoformat(personal_deadline), datetime.min.time()) if personal_deadline else None
        except (ValueError, TypeError):
            pd_dt = None

<<<<<<< HEAD
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
=======
    task = AppTask(
        user_id=bridged_user_id,
        id_name=title,
>>>>>>> 081b93a (function call数据表调用问题修复)
        description=description,
        deadline=due,
        status=status,
        personal_deadline=pd_dt,
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

    logger.info(f"Task created: id={task.id}, id_name={task.id_name}")
    return _task_to_dict(task)


def list_tasks(
    db: Session,
    user_id: int,
    status: Optional[str] = None,
    limit: int = 50,
    **kwargs,
) -> List[Dict[str, Any]]:
    """查询用户的所有任务，返回全部字段信息。

    Args:
        db: 数据库会话
        user_id: 用户 ID
        status: 按状态过滤，不传返回全部
        limit: 最大返回条数，默认 50
        **kwargs: 兼容旧参数（parent_id, parent_id__null），会被静默忽略

    Returns:
        任务列表，每个元素包含任务的全部字段
    """
    # user_id 桥接：task 表中存的是 user 表的 id，需从 users 表 id 转换
    bridged_user_id = _ensure_user_exists(db, user_id)

    q = db.query(AppTask).filter(AppTask.user_id == bridged_user_id)

    if status:
        q = q.filter(AppTask.status == status)

    tasks = (
        q.order_by(AppTask.deadline.asc())
        .limit(limit)
        .all()
    )

    return [_task_to_dict(t) for t in tasks]


def delete_task(
    db: Session,
    task_id: int,
    user_id: int,
) -> Dict[str, Any]:
    """删除任务，同时级联删除其在 sub_task 表中的所有子任务。

    注意：sub_task 表设置了 ForeignKey(ondelete="CASCADE")，
    但为了日志记录和显式控制，这里手动先删子任务再删主任务。

    Args:
        db: 数据库会话
        task_id: 要删除的任务 ID
        user_id: 用户 ID（用于权限校验）

    Returns:
        操作结果 {"ok": True, "deleted_id": int} 或 {"error": str}
    """
    bridged_user_id = _ensure_user_exists(db, user_id)

    task = db.query(AppTask).filter(
        AppTask.id == task_id,
        AppTask.user_id == bridged_user_id,
    ).first()
    if not task:
        return {"error": f"任务 {task_id} 不存在或无权操作"}
    if task.is_final:
        return {"error": "最终节点由流程任务自动维护，不能单独删除"}

    deleted_title = task.id_name

    # 级联删除所有子任务（sub_task 表）
    child_count = (
        db.query(SubTask)
        .filter(SubTask.task_id == task_id)
        .delete(synchronize_session="fetch")
    )

    # 删除父任务自身
    db.delete(task)
    db.commit()

    logger.info(
        f"Task deleted: id={task_id}, id_name={deleted_title}, cascaded_subtasks={child_count}"
    )
    return {
        "ok": True,
        "deleted_id": task_id,
        "deleted_title": deleted_title,
    }


# ═══════════════════════════════════════════════════════════════
# 子任务操作（基于 sub_task 表，3 个函数）
# ═══════════════════════════════════════════════════════════════

def create_subtask(
    db: Session,
    user_id: int,
    task_id: int,
    name: str,
    description: str = "",
    notice_time: Optional[str] = None,
    level: str = "medium",
    status: str = "pending",
    **kwargs,
) -> Dict[str, Any]:
    """为指定任务在 sub_task 表中创建一条子任务记录。

    Args:
        db: 数据库会话
        user_id: 用户 ID（用于校验父任务归属）
        task_id: 所属父任务 ID（task 表的 id）
        name: 子任务名称（必填）
        description: 详细描述
        notice_time: 截止/提醒日期，格式 YYYY-MM-DD
        level: 优先级 low | medium | high | urgent
        status: 状态，默认 "pending"
        **kwargs: 兼容旧参数，会被静默忽略

    Returns:
        包含新子任务完整信息的 dict，或 {"error": str}
    """
    # user_id 桥接
    bridged_user_id = _ensure_user_exists(db, user_id)

    # 权限校验：确认父任务属于该用户
    owner_task = db.query(AppTask).filter(
        AppTask.id == task_id,
        AppTask.user_id == bridged_user_id,
    ).first()
    if not owner_task:
        return {"error": f"任务 {task_id} 不存在或无权操作"}
    if owner_task.task_type != TaskType.process:
        return {"error": "待办事项不能添加子任务，请先创建流程任务"}

    # 解析 notice_time
    try:
        nt = date_type.fromisoformat(notice_time) if notice_time else None
    except (ValueError, TypeError):
        nt = None

<<<<<<< HEAD
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
=======
    subtask = SubTask(
        task_id=task_id,
        name=name,
>>>>>>> 081b93a (function call数据表调用问题修复)
        description=description,
        notice_time=nt,
        level=level,
        status=status,
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
    **kwargs,
) -> List[Dict[str, Any]]:
    """查询子任务列表。只查询 sub_task 表中的记录。

    通过 task_id 关联到 task 表，确保只返回当前用户的子任务。

    Args:
        db: 数据库会话
        user_id: 用户 ID（只返回该用户拥有的子任务）
        task_id: 按父任务 ID 过滤。不传则返回该用户所有子任务
        status: 按状态过滤
        limit: 最大返回条数

    Returns:
        子任务列表，每个元素包含全部字段
    """
    # JOIN task 表以确保只返回当前用户的子任务
    bridged_user_id = _ensure_user_exists(db, user_id)
    q = (
        db.query(SubTask)
        .join(AppTask, SubTask.task_id == AppTask.id)
        .filter(AppTask.user_id == bridged_user_id)
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


def delete_subtask(
    db: Session,
    subtask_id: int,
    user_id: int,
) -> Dict[str, Any]:
    """删除 sub_task 表中的一条子任务记录。

    Args:
        db: 数据库会话
        subtask_id: 要删除的子任务 ID（sub_task 表的 id）
        user_id: 用户 ID（通过 task 表校验权限）

    Returns:
        操作结果 {"ok": True, "deleted_id": int} 或 {"error": str}
    """
    # JOIN task 表确保子任务属于当前用户
    bridged_user_id = _ensure_user_exists(db, user_id)
    subtask = (
        db.query(SubTask)
        .join(AppTask, SubTask.task_id == AppTask.id)
        .filter(SubTask.id == subtask_id, AppTask.user_id == bridged_user_id)
        .first()
    )
    if not subtask:
<<<<<<< HEAD
        return {"error": f"子任务 {subtask_id} 不存在或无权操作（可能不是子任务）"}
    if subtask.is_final:
        return {"error": "最终节点由流程任务自动维护，不能单独删除"}
=======
        return {"error": f"子任务 {subtask_id} 不存在或无权操作"}
>>>>>>> 081b93a (function call数据表调用问题修复)

    deleted_name = subtask.name
    db.delete(subtask)
    db.commit()

    logger.info(f"SubTask deleted: id={subtask_id}, name={deleted_name}")
    return {"ok": True, "deleted_id": subtask_id, "deleted_name": deleted_name}


# ═══════════════════════════════════════════════════════════════
# 工具函数：把 ORM 对象转为纯 dict（便于 JSON 序列化）
# ═══════════════════════════════════════════════════════════════

def _task_to_dict(t: AppTask) -> Dict[str, Any]:
    """AppTask ORM → dict（包含所有字段）"""
    return {
        "id": t.id,
        "user_id": t.user_id,
<<<<<<< HEAD
        "parent_id": t.parent_id,
        "task_type": t.task_type.value if t.task_type else "todo",
        "is_final": bool(t.is_final),
        "title": t.title,
=======
        "id_name": t.id_name,
>>>>>>> 081b93a (function call数据表调用问题修复)
        "description": t.description,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "status": t.status,
        "personal_deadline": t.personal_deadline.isoformat() if t.personal_deadline else None,
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
        "level": st.level,
        "status": st.status,
        "notice_method": st.notice_method,
        "created_at": st.created_at.isoformat() if st.created_at else None,
        "updated_at": st.updated_at.isoformat() if st.updated_at else None,
    }
