"""Credential protection and SSRF-safe retrieval for personal iCalendar feeds."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken

from config import settings


# HTTPX's INFO message includes the complete request URL.  A ManageBac feed
# URL is a bearer credential, so request-level logs must remain disabled.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ManageBac documents this endpoint as an iCal subscription endpoint and its
# Cloudflare edge rejects arbitrary HTTP clients before the request reaches the
# token handler.  Use the legacy iCal compatibility signature that the endpoint
# accepts, while identifying IBuddy explicitly in a separate header instead of
# pretending that the request originated from Google Calendar.
MANAGEBAC_ICAL_USER_AGENT = "iCal/4.0.4"
IBUDDY_CALENDAR_CLIENT = "IBuddy-ManageBac-iCal/1.0"


class ManageBacIntegrationError(Exception):
    def __init__(
        self,
        code: str,
        safe_detail: str,
        *,
        http_status: Optional[int] = None,
        retry_after_seconds: Optional[int] = None,
    ) -> None:
        super().__init__(safe_detail)
        self.code = code
        self.safe_detail = safe_detail[:500]
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


class ManageBacConfigurationError(ManageBacIntegrationError):
    pass


class ManageBacURLValidationError(ManageBacIntegrationError):
    pass


class ManageBacFetchError(ManageBacIntegrationError):
    pass


@dataclass(frozen=True)
class NormalizedFeedURL:
    url: str
    host: str


@dataclass(frozen=True)
class FetchedCalendar:
    http_status: int
    content: bytes
    etag: Optional[str]
    last_modified: Optional[str]
    retry_after_seconds: Optional[int] = None


def _allowed_host(host: str, suffixes: Iterable[str]) -> bool:
    normalized = host.lower().rstrip(".")
    return any(normalized == suffix or normalized.endswith(f".{suffix}") for suffix in suffixes)


def normalize_feed_url(raw_url: str, *, allowed_suffixes: Optional[Iterable[str]] = None) -> NormalizedFeedURL:
    """Normalize webcal to HTTPS and reject credentials or unexpected hosts."""

    value = (raw_url or "").strip()
    if len(value) > 4096:
        raise ManageBacURLValidationError("url_too_long", "iCal 地址过长")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ManageBacURLValidationError("invalid_url", "iCal 地址格式无效") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"webcal", "https"}:
        raise ManageBacURLValidationError("invalid_scheme", "只支持 webcal:// 或 https:// 地址")
    if parsed.username or parsed.password:
        raise ManageBacURLValidationError("embedded_credentials", "iCal 地址不能包含用户名或密码")
    if parsed.fragment:
        raise ManageBacURLValidationError("url_fragment", "iCal 地址不能包含片段标识")

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ManageBacURLValidationError("missing_host", "iCal 地址缺少学校域名")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ManageBacURLValidationError("invalid_port", "iCal 地址端口无效") from exc
    if port not in {None, 443}:
        raise ManageBacURLValidationError("invalid_port", "iCal 地址只允许 HTTPS 默认端口")

    suffixes = tuple(allowed_suffixes or settings.MANAGEBAC_ALLOWED_HOST_SUFFIXES)
    if not suffixes or not _allowed_host(host, suffixes):
        raise ManageBacURLValidationError("host_not_allowed", "该地址不是允许的 ManageBac 域名")
    if not parsed.path or parsed.path == "/":
        raise ManageBacURLValidationError("missing_path", "iCal 地址缺少订阅路径")

    netloc = host if port is None else f"{host}:{port}"
    normalized = urlunsplit(("https", netloc, parsed.path, parsed.query, ""))
    return NormalizedFeedURL(url=normalized, host=host)


def _resolve_host_addresses(host: str) -> list[str]:
    try:
        rows = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ManageBacURLValidationError("dns_failed", "无法解析 ManageBac 学校域名") from exc
    return sorted({row[4][0] for row in rows})


def assert_public_remote_host(
    host: str,
    *,
    resolve_addresses: Optional[Callable[[str], list[str]]] = None,
) -> None:
    """Reject DNS answers that could route a server-side request to a private target."""

    addresses = (resolve_addresses or _resolve_host_addresses)(host)
    if not addresses:
        raise ManageBacURLValidationError("dns_empty", "ManageBac 学校域名没有可用地址")
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ManageBacURLValidationError("dns_invalid", "ManageBac 学校域名解析结果无效") from exc
        if not parsed.is_global:
            raise ManageBacURLValidationError("unsafe_target", "ManageBac 地址解析到了不安全的网络目标")


def _cipher(key: Optional[str] = None) -> Fernet:
    value = (key if key is not None else settings.INTEGRATION_CREDENTIAL_KEY).strip()
    if not value:
        raise ManageBacConfigurationError(
            "credential_key_missing",
            "服务器尚未配置 ManageBac 凭据加密密钥",
        )
    try:
        return Fernet(value.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ManageBacConfigurationError(
            "credential_key_invalid",
            "服务器的 ManageBac 凭据加密密钥无效",
        ) from exc


def encrypt_feed_url(feed_url: str, *, key: Optional[str] = None) -> str:
    return _cipher(key).encrypt(feed_url.encode("utf-8")).decode("ascii")


def decrypt_feed_url(encrypted_value: str, *, key: Optional[str] = None) -> str:
    try:
        return _cipher(key).decrypt(encrypted_value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ManageBacConfigurationError(
            "credential_decrypt_failed",
            "已保存的 ManageBac 连接无法解密，请重新连接",
        ) from exc


def _retry_after_seconds(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return max(1, min(int(value), 86400))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        seconds = int((retry_at - datetime.now(timezone.utc)).total_seconds())
        return max(1, min(seconds, 86400))


async def fetch_calendar(
    raw_url: str,
    *,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    resolve_addresses: Optional[Callable[[str], list[str]]] = None,
) -> FetchedCalendar:
    """Fetch a bounded calendar while validating every redirect target."""

    target = normalize_feed_url(raw_url)
    headers = {
        "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.1",
        "User-Agent": MANAGEBAC_ICAL_USER_AGENT,
        "X-IBuddy-Client": IBUDDY_CALENDAR_CLIENT,
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    timeout = httpx.Timeout(float(settings.MANAGEBAC_HTTP_TIMEOUT_SECONDS))
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        transport=transport,
        trust_env=False,
    ) as client:
        for _redirect_count in range(4):
            await asyncio.to_thread(
                assert_public_remote_host,
                target.host,
                resolve_addresses=resolve_addresses,
            )
            try:
                async with client.stream("GET", target.url, headers=headers) as response:
                    status = response.status_code
                    if status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            raise ManageBacFetchError(
                                "redirect_without_location",
                                "ManageBac 日历返回了无效重定向",
                                http_status=status,
                            )
                        target = normalize_feed_url(urljoin(target.url, location))
                        continue
                    if status == 304:
                        return FetchedCalendar(
                            http_status=304,
                            content=b"",
                            etag=response.headers.get("ETag") or etag,
                            last_modified=response.headers.get("Last-Modified") or last_modified,
                        )
                    if status < 200 or status >= 300:
                        # Never log response bodies, redirect locations, or the
                        # request URL: the URL path contains the bearer token.
                        logger.warning(
                            "ManageBac calendar fetch rejected status=%s host=%s "
                            "content_type=%s server=%s cf_ray=%s",
                            status,
                            target.host,
                            response.headers.get("Content-Type", "")[:120],
                            response.headers.get("Server", "")[:80],
                            response.headers.get("CF-Ray", "")[:120],
                        )
                        raise ManageBacFetchError(
                            f"http_{status}",
                            "ManageBac 日历暂时无法读取",
                            http_status=status,
                            retry_after_seconds=_retry_after_seconds(response.headers.get("Retry-After")),
                        )

                    declared_length = response.headers.get("Content-Length")
                    if declared_length:
                        try:
                            if int(declared_length) > settings.MANAGEBAC_MAX_FEED_BYTES:
                                raise ManageBacFetchError("feed_too_large", "ManageBac 日历文件超过大小限制")
                        except ValueError:
                            pass

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > settings.MANAGEBAC_MAX_FEED_BYTES:
                            raise ManageBacFetchError("feed_too_large", "ManageBac 日历文件超过大小限制")
                    return FetchedCalendar(
                        http_status=status,
                        content=bytes(body),
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        retry_after_seconds=_retry_after_seconds(response.headers.get("Retry-After")),
                    )
            except ManageBacIntegrationError:
                raise
            except httpx.HTTPError as exc:
                raise ManageBacFetchError(
                    "network_error",
                    "连接 ManageBac 日历失败，请稍后重试",
                ) from exc

    raise ManageBacFetchError("too_many_redirects", "ManageBac 日历重定向次数过多")
