import io
import sys
import unittest
from pathlib import Path
from urllib.error import URLError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.registration_readiness import (  # noqa: E402
    CheckResult,
    check_database_schema,
    check_http_health,
    check_python_dependencies,
    check_smtp_configuration,
    collect_readiness,
    exit_code,
    render_results,
)


class FakeResponse:
    status = 200

    def __init__(self, body=b'{"status":"ok"}'):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class RegistrationReadinessTests(unittest.TestCase):
    def test_python_dependencies_report_missing_names(self):
        result = check_python_dependencies(
            finder=lambda name: object() if name != "sqlalchemy" else None
        )
        self.assertFalse(result.ok)
        self.assertIn("sqlalchemy", result.guidance)

    def test_http_health_success_and_failure_are_isolated(self):
        success = check_http_health("后端健康", "unused", opener=lambda *_a, **_k: FakeResponse())
        failure = check_http_health(
            "前端 API 代理",
            "unused",
            opener=lambda *_a, **_k: (_ for _ in ()).throw(URLError("stopped")),
        )
        self.assertTrue(success.ok)
        self.assertFalse(failure.ok)
        self.assertEqual("前端 API 代理", failure.name)

    def test_http_health_rejects_invalid_payload(self):
        result = check_http_health(
            "后端健康",
            "unused",
            opener=lambda *_a, **_k: FakeResponse(b"not-json"),
        )
        self.assertFalse(result.ok)

    def test_database_check_distinguishes_missing_table_and_connection(self):
        self.assertTrue(
            check_database_schema(lambda: ["users", "email_verifications"]).ok
        )
        missing = check_database_schema(lambda: ["users"])
        self.assertFalse(missing.ok)
        self.assertIn("email_verifications", missing.guidance)

        def failed_connection():
            raise RuntimeError("secret connection detail")

        unavailable = check_database_schema(failed_connection)
        self.assertFalse(unavailable.ok)
        self.assertNotIn("secret connection detail", unavailable.guidance)

    def test_smtp_check_supports_external_environment(self):
        result = check_smtp_configuration(
            {
                "SMTP_HOST": "smtp.example.test",
                "SMTP_FROM_EMAIL": "sender@example.test",
                "SMTP_USERNAME": "account",
                "SMTP_PASSWORD": "super-secret",
                "SMTP_PORT": "587",
                "SMTP_USE_STARTTLS": "true",
                "SMTP_USE_SSL": "false",
            }
        )
        self.assertTrue(result.ok)
        self.assertNotIn("super-secret", result.guidance)
        self.assertNotIn("smtp.example.test", result.guidance)

    def test_smtp_check_reports_missing_and_conflicting_settings(self):
        missing = check_smtp_configuration({})
        self.assertFalse(missing.ok)
        self.assertIn("SMTP_HOST", missing.guidance)

        conflict = check_smtp_configuration(
            {
                "SMTP_HOST": "hidden",
                "SMTP_FROM_EMAIL": "hidden",
                "SMTP_USE_STARTTLS": "true",
                "SMTP_USE_SSL": "true",
            }
        )
        self.assertFalse(conflict.ok)
        self.assertIn("不能同时启用", conflict.guidance)

    def test_collect_readiness_keeps_each_layer_separate(self):
        def health(name, _url):
            return CheckResult(name, name == "后端健康", "safe")

        results = collect_readiness(
            "backend",
            "frontend",
            dependency_check=lambda: CheckResult("Python 依赖", True, "safe"),
            health_check=health,
            database_check=lambda: CheckResult("数据库与验证码表", False, "safe"),
            smtp_check=lambda: CheckResult("SMTP 配置", False, "safe"),
        )
        self.assertEqual(
            [
                "Python 依赖",
                "后端健康",
                "前端 API 代理",
                "数据库与验证码表",
                "SMTP 配置",
            ],
            [result.name for result in results],
        )
        self.assertEqual(1, exit_code(results))

    def test_rendered_output_contains_no_secret_values(self):
        secret = "do-not-print-this-secret"
        results = [
            CheckResult("Python 依赖", True, "就绪"),
            CheckResult("SMTP 配置", False, "缺少设置：SMTP_HOST"),
        ]
        stream = io.StringIO()
        render_results(results, stream=stream)
        output = stream.getvalue()
        self.assertIn("NOT READY", output)
        self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()
