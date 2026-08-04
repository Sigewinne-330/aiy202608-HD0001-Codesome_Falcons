import math

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.app_user import AppUser as User
from schemas.user import (
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    VerificationCodeAccepted,
    VerificationCodeRequest,
    VerificationCodeSubmit,
    VerificationProofResponse,
)
from services.auth import create_access_token, get_current_user, hash_password, verify_password
from services.billing import INITIAL_CREDITS, grant_credits
from services.email_service import EmailDeliveryError, EmailSender, get_email_sender
from services.email_verification import (
    GENERIC_ACCEPTED_MESSAGE,
    GENERIC_REGISTRATION_ERROR,
    RegistrationProofError,
    VerificationCodeError,
    VerificationRateLimitError,
    create_verification_request,
    get_registration_proof_for_update,
    mark_delivery_failed,
    mark_delivery_succeeded,
    utcnow,
    verify_code,
)
from services.verification_policy import VerificationPolicy, get_verification_policy


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/verification-codes",
    response_model=VerificationCodeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_verification_code(
    data: VerificationCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    policy: VerificationPolicy = Depends(get_verification_policy),
):
    request_ip = request.client.host if request.client else "unknown"
    try:
        record, code = create_verification_request(
            db, str(data.email), request_ip, policy, settings.SECRET_KEY
        )
    except VerificationRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="验证码请求过于频繁，请稍后重试",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    if code is None:
        # 邮箱已注册：不发送验证码，返回明确提示
        return VerificationCodeAccepted(
            message="该邮箱已注册，请直接登录",
            retry_after_seconds=0,
            already_registered=True,
        )

    try:
        sender.send_verification_code(
            record.email,
            code,
            max(1, math.ceil(policy.code_ttl_seconds / 60)),
        )
    except (EmailDeliveryError, TimeoutError) as exc:
        mark_delivery_failed(db, record)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="验证码暂时无法发送，请稍后重试",
        ) from exc
    mark_delivery_succeeded(db, record)

    return VerificationCodeAccepted(
        message=GENERIC_ACCEPTED_MESSAGE,
        retry_after_seconds=policy.resend_cooldown_seconds,
    )


@router.post("/verification-codes/verify", response_model=VerificationProofResponse)
def submit_verification_code(
    data: VerificationCodeSubmit,
    db: Session = Depends(get_db),
    policy: VerificationPolicy = Depends(get_verification_policy),
):
    try:
        token, expires_in = verify_code(
            db, str(data.email), data.code, policy, settings.SECRET_KEY
        )
    except VerificationCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VerificationProofResponse(
        verification_token=token, expires_in_seconds=expires_in
    )


@router.post("/register", response_model=TokenResponse)
def register(data: UserCreate, db: Session = Depends(get_db)):
    try:
        verification = get_registration_proof_for_update(
            db, str(data.email), data.verification_token
        )
    except RegistrationProofError as exc:
        raise HTTPException(status_code=400, detail=GENERIC_REGISTRATION_ERROR) from exc

    if db.query(User).filter(func.lower(User.email) == str(data.email)).first():
        db.rollback()
        raise HTTPException(status_code=400, detail=GENERIC_REGISTRATION_ERROR)
    if db.query(User).filter(User.username == data.username).first():
        db.rollback()
        raise HTTPException(status_code=400, detail=GENERIC_REGISTRATION_ERROR)

    user = User(
        username=data.username,
        password=hash_password(data.password),
        email=str(data.email),
        nickname=data.nickname,
        grade=data.grade,
        phone_number=data.phone_number,
        wechat_id=data.wechat_id,
    )
    try:
        db.add(user)
        db.flush()
        grant_credits(
            db,
            user,
            INITIAL_CREDITS,
            change_type="gift",
            ref_type="register",
            note=f"新用户注册赠送 {INITIAL_CREDITS} 积分",
        )
        verification.consumed_at = utcnow()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=GENERIC_REGISTRATION_ERROR) from exc
    db.refresh(user)
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter((User.username == data.username) | (User.email == data.username))
        .first()
    )
    if not user or not verify_password(data.password, user.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
