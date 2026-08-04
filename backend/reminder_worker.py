import argparse
import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler

import models  # noqa: F401 - register authoritative metadata
from config import settings
from database import SessionLocal
from services.reminder_orchestrator import ReminderOrchestrator, ReminderRunSummary
from services.schedule_policy import scheduling_enabled


logger = logging.getLogger(__name__)
_last_schedule_analysis_date = None


async def run_once(
    *,
    now_utc: Optional[datetime] = None,
    orchestrator: Optional[ReminderOrchestrator] = None,
    session_factory=SessionLocal,
) -> ReminderRunSummary:
    service = orchestrator or ReminderOrchestrator()
    with session_factory() as db:
        return await service.run(
            db,
            now_utc=now_utc or datetime.now(timezone.utc),
            deliver=True,
        )


def _run_job() -> None:
    global _last_schedule_analysis_date
    try:
        summary = asyncio.run(run_once())
        logger.info(
            "Reminder worker tick evaluated=%s due=%s candidates=%s generated=%s delivered=%s failed=%s",
            summary.evaluated_users,
            summary.due_users,
            summary.candidate_items,
            summary.generated_digests,
            summary.delivered_channels,
            summary.failed_channels,
        )
        # The existing worker is already the project's scheduled background
        # process.  Run the read-only schedule signal once per worker-local
        # day when the feature flag is enabled; auto-apply remains off by
        # policy and uses a separate transactional path.
        local_day = datetime.now(timezone.utc).date()
        if scheduling_enabled() and _last_schedule_analysis_date != local_day:
            from services.schedule_triggers import run_daily_schedule_analysis
            from database import SessionLocal
            with SessionLocal() as db:
                schedule_summary = run_daily_schedule_analysis(db)
            _last_schedule_analysis_date = local_day
            logger.info("Schedule analysis daily signal: %s", schedule_summary)
    except Exception:
        logger.exception("Reminder worker tick failed")


def run_daemon(scheduler=None, job=_run_job) -> None:
    scheduler = scheduler or BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        job,
        "interval",
        seconds=max(10, settings.REMINDER_WORKER_INTERVAL_SECONDS),
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    def stop_worker(*_args):
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    scheduler.start()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run calendar reminder processing")
    parser.add_argument("--once", action="store_true", help="run one tick and exit")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if args.once:
        summary = asyncio.run(run_once())
        print(
            {
                "evaluated_users": summary.evaluated_users,
                "due_users": summary.due_users,
                "candidate_items": summary.candidate_items,
                "generated_digests": summary.generated_digests,
                "delivered_channels": summary.delivered_channels,
                "failed_channels": summary.failed_channels,
            }
        )
        return 0
    run_daemon()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
