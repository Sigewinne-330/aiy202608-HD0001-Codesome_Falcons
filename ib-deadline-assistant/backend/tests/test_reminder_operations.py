import io
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from reminder_worker import run_daemon, run_once  # noqa: E402
from services.registration_readiness import CheckResult  # noqa: E402
from services.reminder_orchestrator import ReminderRunSummary  # noqa: E402
from services.reminder_readiness import (  # noqa: E402
    check_app_base_url,
    check_llm_configuration,
    check_reminder_database,
    check_worker_configuration,
    collect_reminder_readiness,
    render_results,
)


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeWorkerOrchestrator:
    def __init__(self):
        self.calls = []

    async def run(self, db, **kwargs):
        self.calls.append((db, kwargs))
        return ReminderRunSummary(1, 1, 2, 1, 2, 0, False)


class FakeScheduler:
    def __init__(self):
        self.jobs = []
        self.started = False
        self.shutdown_wait = None

    def add_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))

    def start(self):
        self.started = True

    def shutdown(self, wait=True):
        self.shutdown_wait = wait


class ReminderOperationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_once_injects_clock_and_session(self):
        orchestrator = FakeWorkerOrchestrator()
        now = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
        summary = await run_once(
            now_utc=now,
            orchestrator=orchestrator,
            session_factory=FakeSession,
        )
        self.assertEqual(1, summary.generated_digests)
        self.assertEqual(now, orchestrator.calls[0][1]["now_utc"])
        self.assertTrue(orchestrator.calls[0][1]["deliver"])

    def test_daemon_registers_single_job_and_graceful_signals(self):
        scheduler = FakeScheduler()
        handlers = {}

        def register(sig, handler):
            handlers[sig] = handler

        with patch("reminder_worker.signal.signal", side_effect=register):
            run_daemon(scheduler=scheduler, job=lambda: None)
        self.assertTrue(scheduler.started)
        self.assertEqual(1, len(scheduler.jobs))
        self.assertEqual(1, scheduler.jobs[0][1]["max_instances"])
        self.assertTrue(scheduler.jobs[0][1]["coalesce"])
        self.assertEqual(2, len(handlers))
        next(iter(handlers.values()))()
        self.assertFalse(scheduler.shutdown_wait)

    def test_readiness_checks_are_isolated_and_sanitized(self):
        self.assertTrue(
            check_reminder_database(
                lambda: {
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
            ).ok
        )
        self.assertFalse(check_reminder_database(lambda: {"users"}).ok)
        self.assertTrue(check_app_base_url({"APP_BASE_URL": "https://example.test"}).ok)
        self.assertFalse(check_app_base_url({"APP_BASE_URL": "javascript:bad"}).ok)
        self.assertTrue(
            check_worker_configuration({"REMINDER_WORKER_INTERVAL_SECONDS": "60"}).ok
        )
        self.assertFalse(
            check_worker_configuration({"REMINDER_WORKER_INTERVAL_SECONDS": "1"}).ok
        )
        self.assertTrue(check_llm_configuration({"ARK_API_KEY": "present"}).ok)
        self.assertFalse(check_llm_configuration({}).ok)

        results = collect_reminder_readiness(
            database_check=lambda: CheckResult("db", True, "ok"),
            base_url_check=lambda: CheckResult("url", True, "ok"),
            worker_check=lambda: CheckResult("worker", True, "ok"),
            llm_check=lambda: CheckResult("llm", True, "ok"),
            smtp_check=lambda: CheckResult("smtp", False, "missing SMTP_HOST"),
        )
        stream = io.StringIO()
        render_results(results, stream)
        output = stream.getvalue()
        self.assertIn("NOT READY", output)
        self.assertNotIn("present", output)


if __name__ == "__main__":
    unittest.main()
