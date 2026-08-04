import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.email_verification import EmailVerification
from models.app_user import AppUser as User
from services.verification_policy import VerificationPolicy


GENERIC_ACCEPTED_MESSAGE = "如果该邮箱可用于注册，验证码将会发送，请检查收件箱。"
GENERIC_VERIFICATION_ERROR = "验证码无效或已失效，请重新获取。"
GENERIC_REGISTRATION_ERROR = "无法完成注册，请重新验证邮箱后再试。"


class VerificationRateLimitError(RuntimeError):
    def __init__(self, retry_after_seconds: int):
        super().__init__("验证码请求过于频繁")
        self.retry_after_seconds = max(1, retry_after_seconds)


class VerificationCodeError(RuntimeError):
    pass


class RegistrationProofError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _code_digest(email: str, code: str, salt: str, secret_key: str) -> str:
    payload = f"{salt}:{normalize_email(email)}:{code}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_verification_request(
    db: Session,
    email: str,
    request_ip: str,
    policy: VerificationPolicy,
    secret_key: str,
) -> tuple[EmailVerification, str | None]:
    now = utcnow()
    email = normalize_email(email)
    request_ip = request_ip or "unknown"
    hour_ago = now - timedelta(hours=1)

    ip_count = (
        db.query(func.count(EmailVerification.id))
        .filter(
            EmailVerification.request_ip == request_ip,
            EmailVerification.created_at >= hour_ago,
        )
        .scalar()
        or 0
    )
    if ip_count >= policy.ip_limit_per_hour:
        raise VerificationRateLimitError(3600)

    registered = (
        db.query(User.id).filter(func.lower(User.email) == email).first() is not None
    )

    limited_statuses = ("sent", "suppressed")
    last_request = (
        db.query(EmailVerification)
        .filter(
            EmailVerification.email == email,
            EmailVerification.delivery_status.in_(limited_statuses),
        )
        .order_by(
            EmailVerification.created_at.desc(),
            EmailVerification.id.desc(),
        )
        .first()
    )
    if last_request and last_request.created_at:
        elapsed = (now - last_request.created_at).total_seconds()
        # 防御：如果 elapsed < 0（时区不一致等异常情况），视为冷却已过期
        if elapsed < 0:
            pass
        elif elapsed < policy.resend_cooldown_seconds:
            raise VerificationRateLimitError(
                math.ceil(policy.resend_cooldown_seconds - elapsed)
            )

    email_count = (
        db.query(func.count(EmailVerification.id))
        .filter(
            EmailVerification.email == email,
            EmailVerification.delivery_status.in_(limited_statuses),
            EmailVerification.created_at >= hour_ago,
        )
        .scalar()
        or 0
    )
    if email_count >= policy.email_limit_per_hour:
        raise VerificationRateLimitError(3600)

    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    record = EmailVerification(
        email=email,
        code_salt=salt,
        code_digest=_code_digest(email, code, salt, secret_key),
        request_ip=request_ip[:45],
        delivery_status="suppressed" if registered else "pending",
        expires_at=now + timedelta(seconds=policy.code_ttl_seconds),
        invalidated_at=now if registered else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, None if registered else code


def mark_delivery_succeeded(db: Session, record: EmailVerification) -> None:
    now = utcnow()
    newer_sent_exists = (
        db.query(EmailVerification.id)
        .filter(
            EmailVerification.email == record.email,
            EmailVerification.id > record.id,
            EmailVerification.delivery_status == "sent",
            EmailVerification.invalidated_at.is_(None),
        )
        .first()
        is not None
    )
    (
        db.query(EmailVerification)
        .filter(
            EmailVerification.email == record.email,
            EmailVerification.id < record.id,
            EmailVerification.delivery_status == "sent",
            EmailVerification.invalidated_at.is_(None),
        )
        .update({EmailVerification.invalidated_at: now}, synchronize_session=False)
    )
    record.delivery_status = "sent"
    record.invalidated_at = now if newer_sent_exists else None
    db.commit()


def mark_delivery_failed(db: Session, record: EmailVerification) -> None:
    now = utcnow()
    record.delivery_status = "failed"
    record.invalidated_at = now
    db.commit()


def verify_code(
    db: Session,
    email: str,
    code: str,
    policy: VerificationPolicy,
    secret_key: str,
) -> tuple[str, int]:
    now = utcnow()
    email = normalize_email(email)
    record = (
        db.query(EmailVerification)
        .filter(
            EmailVerification.email == email,
            EmailVerification.delivery_status == "sent",
            EmailVerification.invalidated_at.is_(None),
        )
        .order_by(
            EmailVerification.created_at.desc(),
            EmailVerification.id.desc(),
        )
        .with_for_update()
        .first()
    )

    if (
        not record
        or record.expires_at <= now
        or record.verified_at is not None
        or record.failed_attempts >= policy.max_attempts
    ):
        raise VerificationCodeError(GENERIC_VERIFICATION_ERROR)

    submitted_digest = _code_digest(email, code, record.code_salt, secret_key)
    if not hmac.compare_digest(submitted_digest, record.code_digest):
        record.failed_attempts += 1
        if record.failed_attempts >= policy.max_attempts:
            record.invalidated_at = now
        db.commit()
        raise VerificationCodeError(GENERIC_VERIFICATION_ERROR)

    token = secrets.token_urlsafe(32)
    record.registration_token_digest = _token_digest(token)
    record.verified_at = now
    record.proof_expires_at = now + timedelta(seconds=policy.proof_ttl_seconds)
    db.commit()
    return token, policy.proof_ttl_seconds


def get_registration_proof_for_update(
    db: Session, email: str, token: str
) -> EmailVerification:
    now = utcnow()
    email = normalize_email(email)
    record = (
        db.query(EmailVerification)
        .filter(EmailVerification.registration_token_digest == _token_digest(token))
        .with_for_update()
        .first()
    )
    if (
        not record
        or record.email != email
        or record.verified_at is None
        or record.proof_expires_at is None
        or record.proof_expires_at <= now
        or record.consumed_at is not None
        or record.invalidated_at is not None
    ):
        raise RegistrationProofError(GENERIC_REGISTRATION_ERROR)
    return record
