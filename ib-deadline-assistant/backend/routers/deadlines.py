from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from datetime import date, timedelta
from database import get_db
from models.user import User
from models.deadline import Deadline as DeadlineModel, DeadlineStatus
from schemas.deadline import DeadlineCreate, DeadlineUpdate, DeadlineResponse, CollisionCheckRequest
from services.auth import get_current_user

router = APIRouter(prefix="/api/deadlines", tags=["deadlines"])


@router.get("", response_model=List[DeadlineResponse])
def list_deadlines(
    status: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(DeadlineModel).filter(DeadlineModel.user_id == current_user.id)
    if status:
        query = query.filter(DeadlineModel.status == status)
    deadlines = query.order_by(DeadlineModel.due_date.asc()).all()
    return [DeadlineResponse.model_validate(d) for d in deadlines]


@router.post("", response_model=DeadlineResponse)
def create_deadline(
    data: DeadlineCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deadline = DeadlineModel(user_id=current_user.id, **data.model_dump())
    db.add(deadline)
    db.commit()
    db.refresh(deadline)
    return DeadlineResponse.model_validate(deadline)


@router.put("/{deadline_id}", response_model=DeadlineResponse)
def update_deadline(
    deadline_id: int,
    data: DeadlineUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deadline = db.query(DeadlineModel).filter(
        DeadlineModel.id == deadline_id, DeadlineModel.user_id == current_user.id
    ).first()
    if not deadline:
        raise HTTPException(status_code=404, detail="Deadline 不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(deadline, key, value)
    db.commit()
    db.refresh(deadline)
    return DeadlineResponse.model_validate(deadline)


@router.delete("/{deadline_id}")
def delete_deadline(
    deadline_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deadline = db.query(DeadlineModel).filter(
        DeadlineModel.id == deadline_id, DeadlineModel.user_id == current_user.id
    ).first()
    if not deadline:
        raise HTTPException(status_code=404, detail="Deadline 不存在")
    db.delete(deadline)
    db.commit()
    return {"ok": True}


@router.get("/check/collisions")
def check_collisions(
    date_str: str = Query(alias="date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检查某日是否有多个 deadline 冲突"""
    check_date = date.fromisoformat(date_str)
    conflicts = db.query(DeadlineModel).filter(
        DeadlineModel.user_id == current_user.id,
        DeadlineModel.due_date == check_date,
        DeadlineModel.status == DeadlineStatus.pending,
    ).all()

    return {
        "date": date_str,
        "count": len(conflicts),
        "overload": len(conflicts) >= 3,
        "deadlines": [DeadlineResponse.model_validate(d) for d in conflicts],
        "suggestion": (
            f"⚠️ {date_str} 有 {len(conflicts)} 个截止日期，建议提前规划，分散完成时间。"
            if len(conflicts) >= 3
            else None
        ),
    }


@router.get("/upcoming", response_model=List[DeadlineResponse])
def upcoming_deadlines(
    days: int = Query(default=7),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取未来 N 天内的 deadline"""
    today = date.today()
    end_date = today + timedelta(days=days)
    deadlines = db.query(DeadlineModel).filter(
        DeadlineModel.user_id == current_user.id,
        DeadlineModel.due_date >= today,
        DeadlineModel.due_date <= end_date,
        DeadlineModel.status == DeadlineStatus.pending,
    ).order_by(DeadlineModel.due_date.asc()).all()
    return [DeadlineResponse.model_validate(d) for d in deadlines]
