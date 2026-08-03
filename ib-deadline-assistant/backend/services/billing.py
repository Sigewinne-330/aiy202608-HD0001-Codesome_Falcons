"""积分计费核心逻辑：1 积分 = 1000 token

- 注册赠送初始积分
- 每次 AI 调用按实际 token 消耗扣积分（最少扣 1 积分）
- 充值 / 赠送 / 消耗均写入 token_ledger 流水
"""
import math
from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.token_ledger import TokenLedger

INITIAL_CREDITS = 10000          # 新用户注册赠送积分
TOKENS_PER_CREDIT = 1000         # 1 积分 = 1000 token
MIN_CREDITS_BALANCE = 0          # 余额阈值（<=0 拒绝服务）

# 充值档位（模拟支付；真实支付时替换为渠道配置）
RECHARGE_PLANS = [
    {"code": "p6", "amount": 6.0, "credits": 6000, "bonus": "基础包"},
    {"code": "p30", "amount": 30.0, "credits": 32000, "bonus": "热门包"},
    {"code": "p68", "amount": 68.0, "credits": 75000, "bonus": "进阶包"},
    {"code": "p128", "amount": 128.0, "credits": 150000, "bonus": "学霸包"},
]


def credits_for_tokens(tokens: int) -> int:
    """token 数 → 积分（向上取整，最少 1 积分）"""
    if tokens <= 0:
        return 0
    return max(1, math.ceil(tokens / TOKENS_PER_CREDIT))


def ensure_balance(user) -> None:
    """发送消息前检查余额，不足则 402"""
    if user.balance <= MIN_CREDITS_BALANCE:
        raise HTTPException(
            status_code=402,
            detail="余额不足，请先充值后再使用 AI 助手",
        )


def deduct_credits(
    db: Session,
    user,
    tokens: int,
    ref_id: int | None = None,
    note: str = "",
) -> int:
    """扣减积分并写流水；余额不足抛 402"""
    credits = credits_for_tokens(tokens)
    if credits <= 0:
        return 0
    if user.balance < credits:
        raise HTTPException(status_code=402, detail="余额不足，请先充值后再使用 AI 助手")

    user.balance -= credits
    db.add(TokenLedger(
        user_id=user.id,
        change_type="consume",
        change_amount=-credits,
        balance_after=user.balance,
        ref_id=ref_id,
        ref_type="chat",
        note=note or f"AI 对话消耗 {tokens} tokens",
    ))
    return credits


def grant_credits(
    db: Session,
    user,
    credits: int,
    change_type: str = "gift",
    ref_id: int | None = None,
    ref_type: str = "register",
    note: str = "",
) -> int:
    """增加积分（注册赠送 / 充值到账）并写流水"""
    if credits <= 0:
        return 0
    user.balance += credits
    db.add(TokenLedger(
        user_id=user.id,
        change_type=change_type,
        change_amount=credits,
        balance_after=user.balance,
        ref_id=ref_id,
        ref_type=ref_type,
        note=note,
    ))
    return credits
