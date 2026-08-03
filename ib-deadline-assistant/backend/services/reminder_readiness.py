import os
import sys
from typing import Callable, Iterable, Mapping, Sequence, TextIO
from urllib.parse import urlparse

from services.registration_readiness import CheckResult, check_smtp_configuration


REQUIRED_TABLES = {
    "users",
    "tasks",
    "deadlines",
    "chat_history",
    "reminder_role_cards",
    "reminder_preferences",
    "reminder_occurrences",
    "reminder_digests",
    "reminder_deliveries",
    "llm_usage_records",
}


def _pass(name: str, guidance: str = "就绪") -> CheckResult:
    return CheckResult(name, True, guidance)


def _fail(name: str, guidance: str) -> CheckResult:
    return CheckResult(name, False, guidance)


def check_reminder_database(
    table_names_loader: Callable[[], Iterable[str]] | None = None,
) -> CheckResult:
    try:
        if table_names_loader is None:
            from sqlalchemy import inspect

            from database import engine

            table_names = set(inspect(engine).get_table_names())
        else:
            table_names = set(table_names_loader())
    except Exception:
        return _fail("提醒数据库结构", "无法连接数据库；请检查 MySQL 与数据库配置")
    missing = sorted(REQUIRED_TABLES - table_names)
    if missing:
        return _fail("提醒数据库结构", "缺少表：" + ", ".join(missing))
    return _pass("提醒数据库结构")


def check_app_base_url(environ: Mapping[str, str] | None = None) -> CheckResult:
    env = os.environ if environ is None else environ
    value = env.get("APP_BASE_URL", "http://localhost:5173").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _fail("聊天链接配置", "APP_BASE_URL 必须是 http(s) 绝对地址")
    return _pass("聊天链接配置")


def check_worker_configuration(environ: Mapping[str, str] | None = None) -> CheckResult:
    env = os.environ if environ is None else environ
    try:
        interval = int(env.get("REMINDER_WORKER_INTERVAL_SECONDS", "60"))
    except ValueError:
        return _fail("提醒 Worker 配置", "REMINDER_WORKER_INTERVAL_SECONDS 必须是整数")
    if interval < 10:
        return _fail("提醒 Worker 配置", "Worker 间隔不得小于 10 秒")
    return _pass("提醒 Worker 配置")


def check_llm_configuration(environ: Mapping[str, str] | None = None) -> CheckResult:
    env = os.environ if environ is None else environ
    if not env.get("ARK_API_KEY", "").strip() and not env.get(
        "DEEPSEEK_API_KEY", ""
    ).strip():
        return _fail("提醒 LLM 配置", "至少配置一个 LLM API key；否则只会使用固定模板")
    return _pass("提醒 LLM 配置", "至少一个提供商已配置；真实生成仍需 provider smoke test")


def collect_reminder_readiness(
    *,
    database_check: Callable[[], CheckResult] = check_reminder_database,
    base_url_check: Callable[[], CheckResult] = check_app_base_url,
    worker_check: Callable[[], CheckResult] = check_worker_configuration,
    llm_check: Callable[[], CheckResult] = check_llm_configuration,
    smtp_check: Callable[[], CheckResult] = check_smtp_configuration,
) -> list[CheckResult]:
    return [database_check(), base_url_check(), worker_check(), llm_check(), smtp_check()]


def render_results(results: Sequence[CheckResult], stream: TextIO = sys.stdout) -> None:
    for result in results:
        print(
            f"[{'PASS' if result.ok else 'FAIL'}] {result.name} - {result.guidance}",
            file=stream,
        )
    print(
        "READY: 可以运行真实提醒验收"
        if all(result.ok for result in results)
        else "NOT READY: 自动化测试仍可运行；真实 provider 验收尚未就绪",
        file=stream,
    )


def main() -> int:
    results = collect_reminder_readiness()
    render_results(results)
    return 0 if all(result.ok for result in results) else 1
