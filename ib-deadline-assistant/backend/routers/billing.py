"""计费 / 充值 API：余额概览、用量统计、流水、充值订单（模拟支付）"""
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.app_user import AppUser as User
from models.token_ledger import TokenLedger
from models.billing_order import BillingOrder
from services.auth import get_current_user
from services.billing import (
    RECHARGE_PLANS,
    TOKENS_PER_CREDIT,
    grant_credits,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/summary")
def billing_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """余额概览：当前余额、今日/本月消耗、按近 7 天速度估算可用天数"""
    today_start = datetime.combine(date.today(), datetime.min.time())
    month_start = today_start.replace(day=1)
    week_ago = today_start - timedelta(days=6)

    def spent_since(since):
        row = db.query(func.sum(TokenLedger.change_amount)).filter(
            TokenLedger.user_id == current_user.id,
            TokenLedger.change_type == "consume",
            TokenLedger.created_at >= since,
        ).scalar()
        return -int(row or 0)

    today_spent = spent_since(today_start)
    month_spent = spent_since(month_start)
    week_spent = spent_since(week_ago)

    # 估算可用天数：近 7 天日均消耗
    days_left = None
    if week_spent > 0 and current_user.balance > 0:
        daily = week_spent / 7
        days_left = max(1, int(current_user.balance / daily)) if daily > 0 else None

    return {
        "balance": current_user.balance or 0,
        "tokens_per_credit": TOKENS_PER_CREDIT,
        "today_spent": today_spent,
        "month_spent": month_spent,
        "week_spent": week_spent,
        "estimated_days_left": days_left,
    }


@router.get("/usage")
def billing_usage(
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """近 N 天每日消耗（柱状图数据）"""
    days = max(1, min(90, days))
    since = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())

    rows = db.query(
        func.date(TokenLedger.created_at).label("d"),
        func.sum(TokenLedger.change_amount).label("total"),
    ).filter(
        TokenLedger.user_id == current_user.id,
        TokenLedger.change_type == "consume",
        TokenLedger.created_at >= since,
    ).group_by("d").all()

    spent_map = {str(r.d): -int(r.total or 0) for r in rows}

    result = []
    for i in range(days):
        day = date.today() - timedelta(days=days - 1 - i)
        result.append({"date": day.isoformat(), "spent": spent_map.get(day.isoformat(), 0)})
    return {"days": result}


@router.get("/ledger")
def billing_ledger(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """积分流水（充值 / 消耗 / 赠送），按时间倒序"""
    rows = (
        db.query(TokenLedger)
        .filter(TokenLedger.user_id == current_user.id)
        .order_by(TokenLedger.id.desc())
        .offset(offset)
        .limit(min(limit, 100))
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "change_type": r.change_type,
                "change_amount": r.change_amount,
                "balance_after": r.balance_after,
                "ref_type": r.ref_type,
                "note": r.note,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/plans")
def list_plans():
    """充值档位列表"""
    return {"plans": RECHARGE_PLANS}


@router.post("/orders")
def create_order(
    plan_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建充值订单（模拟支付：创建后直接视为待支付）"""
    plan = next((p for p in RECHARGE_PLANS if p["code"] == plan_code), None)
    if not plan:
        raise HTTPException(status_code=400, detail="无效的充值档位")

    order = BillingOrder(
        user_id=current_user.id,
        plan_code=plan["code"],
        amount=plan["amount"],
        credits=plan["credits"],
        status="pending",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return {
        "id": order.id,
        "plan_code": order.plan_code,
        "amount": order.amount,
        "credits": order.credits,
        "status": order.status,
    }


@router.post("/orders/{order_id}/pay")
def pay_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """模拟支付确认：订单状态置为 paid 并给余额到账 + 写流水"""
    order = (
        db.query(BillingOrder)
        .filter(BillingOrder.id == order_id, BillingOrder.user_id == current_user.id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == "paid":
        raise HTTPException(status_code=400, detail="订单已支付，请勿重复操作")

    order.status = "paid"
    order.paid_at = datetime.now()
    grant_credits(
        db, current_user, order.credits,
        change_type="recharge",
        ref_id=order.id,
        ref_type="order",
        note=f"充值 {order.credits} 积分（¥{order.amount:g}）",
    )
    db.commit()
    db.refresh(order)
    return {
        "id": order.id,
        "status": order.status,
        "credits": order.credits,
        "balance": current_user.balance,
    }
