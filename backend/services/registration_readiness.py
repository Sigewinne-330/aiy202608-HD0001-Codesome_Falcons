"""Read-only runtime checks for the registration email-verification flow."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


REQUIRED_MODULES = (
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "pymysql",
    "dotenv",
)
REQUIRED_SMTP_SETTINGS = ("SMTP_HOST", "SMTP_FROM_EMAIL")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    guidance: str


def _pass(name: str, guidance: str = "就绪") -> CheckResult:
    return CheckResult(name=name, ok=True, guidance=guidance)


def _fail(name: str, guidance: str) -> CheckResult:
    return CheckResult(name=name, ok=False, guidance=guidance)


def load_backend_environment() -> None:
    """Load backend/.env when present; externally injected values keep priority."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(backend_dir / ".env", override=False)


def check_python_dependencies(
    finder: Callable[[str], object | None] = importlib.util.find_spec,
) -> CheckResult:
    missing = [name for name in REQUIRED_MODULES if finder(name) is None]
    if missing:
        return _fail(
            "Python 依赖",
            "缺少模块：" + ", ".join(missing) + "；请在项目虚拟环境安装 requirements.txt",
        )
    return _pass("Python 依赖")


def check_http_health(
    name: str,
    url: str,
    opener: Callable[..., object] = urlopen,
) -> CheckResult:
    try:
        with opener(url, timeout=3) as response:
            status = getattr(response, "status", None)
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return _fail(name, "无法取得有效健康响应；请启动对应服务并检查端口或代理配置")

    if status != 200 or payload.get("status") != "ok":
        return _fail(name, "健康响应内容异常；请检查服务日志和路由配置")
    return _pass(name)


def check_database_schema(
    table_names_loader: Callable[[], Iterable[str]] | None = None,
) -> CheckResult:
    try:
        if table_names_loader is None:
            from sqlalchemy import inspect

            from database import engine

            table_names = inspect(engine).get_table_names()
        else:
            table_names = table_names_loader()
    except Exception:
        return _fail("数据库与验证码表", "无法连接数据库；请启动 MySQL 并检查数据库环境配置")

    if "email_verifications" not in set(table_names):
        return _fail(
            "数据库与验证码表",
            "缺少 email_verifications 表；请执行初始化脚本或启动后端完成建表",
        )
    return _pass("数据库与验证码表")


def _parse_bool(name: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是布尔值")


def check_smtp_configuration(
    environ: Mapping[str, str] | None = None,
) -> CheckResult:
    env = os.environ if environ is None else environ
    missing = [name for name in REQUIRED_SMTP_SETTINGS if not env.get(name, "").strip()]
    if missing:
        return _fail("SMTP 配置", "缺少设置：" + ", ".join(missing))

    username_present = bool(env.get("SMTP_USERNAME", "").strip())
    password_present = bool(env.get("SMTP_PASSWORD", "").strip())
    if username_present != password_present:
        return _fail("SMTP 配置", "SMTP_USERNAME 与 SMTP_PASSWORD 必须同时配置或同时留空")

    try:
        port = int(env.get("SMTP_PORT", "587"))
        if port <= 0:
            raise ValueError
        use_starttls = _parse_bool(
            "SMTP_USE_STARTTLS", env.get("SMTP_USE_STARTTLS", "true")
        )
        use_ssl = _parse_bool("SMTP_USE_SSL", env.get("SMTP_USE_SSL", "false"))
    except ValueError:
        return _fail("SMTP 配置", "SMTP 端口或 TLS/SSL 布尔设置无效")

    if use_starttls and use_ssl:
        return _fail("SMTP 配置", "SMTP_USE_STARTTLS 与 SMTP_USE_SSL 不能同时启用")
    return _pass("SMTP 配置", "必需设置已提供；实际认证与投递仍需真实邮件验收")


def collect_readiness(
    backend_url: str,
    frontend_url: str,
    *,
    dependency_check: Callable[[], CheckResult] = check_python_dependencies,
    health_check: Callable[[str, str], CheckResult] = check_http_health,
    database_check: Callable[[], CheckResult] = check_database_schema,
    smtp_check: Callable[[], CheckResult] = check_smtp_configuration,
) -> list[CheckResult]:
    return [
        dependency_check(),
        health_check("后端健康", backend_url),
        health_check("前端 API 代理", frontend_url),
        database_check(),
        smtp_check(),
    ]


def render_results(results: Sequence[CheckResult], stream: TextIO = sys.stdout) -> None:
    for result in results:
        label = "PASS" if result.ok else "FAIL"
        print(f"[{label}] {result.name} - {result.guidance}", file=stream)
    if all(result.ok for result in results):
        print("READY: 可以开始真实邮箱验证码验收", file=stream)
    else:
        print("NOT READY: 修复上述失败项后再进行真实邮箱验收", file=stream)


def exit_code(results: Sequence[CheckResult]) -> int:
    return 0 if all(result.ok for result in results) else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查注册邮箱验证运行环境")
    parser.add_argument(
        "--backend-url",
        default="http://127.0.0.1:8000/api/health",
        help="后端健康检查地址",
    )
    parser.add_argument(
        "--frontend-url",
        default="http://127.0.0.1:5173/api/health",
        help="经前端代理访问的健康检查地址",
    )
    args = parser.parse_args(argv)

    load_backend_environment()
    results = collect_readiness(args.backend_url, args.frontend_url)
    render_results(results)
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
