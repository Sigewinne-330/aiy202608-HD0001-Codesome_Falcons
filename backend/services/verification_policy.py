import os
from dataclasses import dataclass


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


@dataclass(frozen=True)
class VerificationPolicy:
    code_ttl_seconds: int = 600
    proof_ttl_seconds: int = 900
    max_attempts: int = 5
    resend_cooldown_seconds: int = 60
    email_limit_per_hour: int = 5
    ip_limit_per_hour: int = 20

    @classmethod
    def from_env(cls) -> "VerificationPolicy":
        return cls(
            code_ttl_seconds=_positive_int("EMAIL_VERIFICATION_CODE_TTL_SECONDS", 600),
            proof_ttl_seconds=_positive_int("EMAIL_VERIFICATION_PROOF_TTL_SECONDS", 900),
            max_attempts=_positive_int("EMAIL_VERIFICATION_MAX_ATTEMPTS", 5),
            resend_cooldown_seconds=_positive_int(
                "EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS", 60
            ),
            email_limit_per_hour=_positive_int(
                "EMAIL_VERIFICATION_EMAIL_LIMIT_PER_HOUR", 5
            ),
            ip_limit_per_hour=_positive_int(
                "EMAIL_VERIFICATION_IP_LIMIT_PER_HOUR", 20
            ),
        )


def get_verification_policy() -> VerificationPolicy:
    return VerificationPolicy.from_env()

