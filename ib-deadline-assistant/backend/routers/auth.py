from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.app_user import AppUser as User
from schemas.user import UserCreate, UserLogin, UserResponse, TokenResponse
from services.auth import hash_password, verify_password, create_access_token, get_current_user
from services.billing import INITIAL_CREDITS, grant_credits

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="用户名已被使用")
    if data.email and db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    user = User(
        username=data.username,
        password=hash_password(data.password),
        email=data.email,
        nickname=data.nickname,
        grade=data.grade,
        phone_number=data.phone_number,
        wechat_id=data.wechat_id,
    )
    db.add(user)
    db.flush()
    # 注册赠送初始积分（写流水留痕，balance 由 grant_credits 累加）
    grant_credits(
        db, user, INITIAL_CREDITS,
        change_type="gift",
        ref_type="register",
        note=f"新用户注册赠送 {INITIAL_CREDITS} 积分",
    )
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
    """登录：支持用户名或邮箱 + 密码"""
    user = (
        db.query(User)
        .filter((User.username == data.username) | (User.email == data.username))
        .first()
    )
    if not user or not verify_password(data.password, user.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
