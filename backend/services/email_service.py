import logging
import os
import smtplib
import socket
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional, Protocol

from services.email_templates import render_verification_code

logger = logging.getLogger(__name__)


def _as_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是布尔值")


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
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_starttls: bool
    use_ssl: bool
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "SMTPConfig":
        config = cls(
            host=os.getenv("SMTP_HOST", "").strip(),
            port=_positive_int("SMTP_PORT", 587),
            username=os.getenv("SMTP_USERNAME", "").strip(),
            password=os.getenv("SMTP_PASSWORD", ""),
            from_email=os.getenv("SMTP_FROM_EMAIL", "").strip(),
            from_name="IBuddy",
            use_starttls=_as_bool("SMTP_USE_STARTTLS", True),
            use_ssl=_as_bool("SMTP_USE_SSL", False),
            timeout_seconds=_positive_int("SMTP_TIMEOUT_SECONDS", 10),
        )
        if config.use_starttls and config.use_ssl:
            raise ValueError("SMTP_USE_STARTTLS 与 SMTP_USE_SSL 不能同时启用")
        return config


class EmailDeliveryError(RuntimeError):
    def __init__(self, message: str, *, code: str = "smtp_failed", retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class GenericEmailMessage:
    recipient: str
    subject: str
    body: str
    html_body: Optional[str] = None


class EmailSender(Protocol):
    def send_verification_code(
        self, recipient: str, code: str, expires_in_minutes: int
    ) -> None: ...


class EmailTransport(Protocol):
    def send_message(self, message: GenericEmailMessage) -> Optional[str]: ...


class SMTPEmailSender:
    def __init__(self, config: SMTPConfig):
        self.config = config

    def send_verification_code(
        self, recipient: str, code: str, expires_in_minutes: int
    ) -> None:
        self.send_message(
            GenericEmailMessage(
                recipient=recipient,
                subject="注册邮箱验证码",
                body=(
                    "你的注册验证码是："
                    f"{code}\n\n验证码将在 {expires_in_minutes} 分钟后失效，"
                    "请勿将验证码转发给他人。"
                ),
                html_body=render_verification_code(code, expires_in_minutes),
            )
        )

    def send_message(self, message_data: GenericEmailMessage) -> Optional[str]:
        if not self.config.host or not self.config.from_email:
            raise EmailDeliveryError(
                "SMTP 邮件服务未配置", code="smtp_not_configured", retryable=False
            )

        try:
            message = EmailMessage()
            message["Subject"] = message_data.subject
            message["From"] = formataddr(
                (self.config.from_name, self.config.from_email)
            )
            message["To"] = message_data.recipient
            message.set_content(message_data.body)
            if message_data.html_body:
                message.add_alternative(message_data.html_body, subtype="html")

            smtp_class = smtplib.SMTP_SSL if self.config.use_ssl else smtplib.SMTP
            with smtp_class(
                self.config.host,
                self.config.port,
                timeout=self.config.timeout_seconds,
            ) as client:
                if self.config.use_starttls:
                    client.starttls()
                if self.config.username:
                    client.login(self.config.username, self.config.password)
                client.send_message(message)
            return message.get("Message-ID")
        except smtplib.SMTPAuthenticationError as exc:
            logger.warning("SMTP authentication rejected")
            raise EmailDeliveryError(
                "SMTP 认证失败", code="smtp_auth_failed", retryable=False
            ) from exc
        except (ValueError, UnicodeError) as exc:
            logger.warning("Email headers or content are invalid")
            raise EmailDeliveryError(
                "邮件内容无效", code="email_content_invalid", retryable=False
            ) from exc
        except (
            smtplib.SMTPException,
            OSError,
            socket.timeout,
        ) as exc:
            logger.warning("SMTP delivery failed")
            raise EmailDeliveryError(
                "邮件发送失败", code="smtp_transient_failure", retryable=True
            ) from exc


class UnavailableEmailSender:
    def __init__(self, reason: str):
        self.reason = reason

    def send_verification_code(
        self, recipient: str, code: str, expires_in_minutes: int
    ) -> None:
        raise EmailDeliveryError(
            self.reason, code="smtp_not_configured", retryable=False
        )

    def send_message(self, message: GenericEmailMessage) -> Optional[str]:
        raise EmailDeliveryError(
            self.reason, code="smtp_not_configured", retryable=False
        )


def get_email_sender() -> EmailSender:
    try:
        return SMTPEmailSender(SMTPConfig.from_env())
    except ValueError:
        logger.warning("SMTP configuration is invalid")
        return UnavailableEmailSender("SMTP 邮件服务配置无效")


def get_email_transport() -> EmailTransport:
    return get_email_sender()
