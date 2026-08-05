import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.schedule_personalization import SchedulingGovernanceJob  # noqa: E402
from services.schedule_personalization_monitoring import (  # noqa: E402
    evaluate_monitoring_window,
    record_monitoring_snapshot,
)
from services.schedule_personalization_operations import global_kill_active  # noqa: E402


def healthy_metrics():
    return {
        "hard_constraint_violations": 0,
        "deadline_miss_rate_degradation": 0,
        "effort_p90_coverage": 0.9,
        "risk_ece": 0.05,
        "override_rate": 0.2,
        "undo_rate": 0.1,
        "false_intervention_rate": 0.1,
        "p95_latency_ms": 50,
        "update_failure_rate": 0,
        "drifted_scope_share": 0.1,
        "maximum_slice_disparity_gap": 0.05,
        "deletion_correctness_rate": 1,
        "deleted_evidence_served_count": 0,
    }


class PersonalizationMonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.end = datetime(2026, 8, 5, 12)
        self.start = self.end - timedelta(days=7)

    def test_every_required_signal_has_actionable_runbook_metadata(self):
        snapshot = evaluate_monitoring_window(
            window_start=self.start, window_end=self.end, metrics=healthy_metrics()
        )
        self.assertEqual(13, len(snapshot.alerts))
        self.assertFalse(snapshot.requires_global_kill)
        self.assertTrue(all(item.status == "healthy" for item in snapshot.alerts))
        for alert in snapshot.alerts:
            self.assertTrue(alert.owner and alert.threshold and alert.evaluation_window)
            self.assertTrue(alert.response and alert.recovery and alert.runbook)

    def test_synthetic_warning_alerts_trigger_and_recover(self):
        metrics = healthy_metrics()
        metrics.update({"risk_ece": 0.2, "p95_latency_ms": 100, "drifted_scope_share": 0.5})
        firing = evaluate_monitoring_window(
            window_start=self.start, window_end=self.end, metrics=metrics
        )
        firing_keys = frozenset(item.key for item in firing.alerts if item.status == "firing")
        self.assertEqual({"risk_calibration", "serving_latency", "drift"}, set(firing_keys))
        recovered = evaluate_monitoring_window(
            window_start=self.end,
            window_end=self.end + timedelta(days=7),
            metrics=healthy_metrics(),
            previous_firing=firing_keys,
        )
        self.assertEqual(
            firing_keys,
            frozenset(item.key for item in recovered.alerts if item.status == "recovered"),
        )

    def test_critical_alert_and_monitoring_outage_kill_only_learned_influence(self):
        metrics = healthy_metrics()
        metrics["deleted_evidence_served_count"] = 1
        snapshot = evaluate_monitoring_window(
            window_start=self.start, window_end=self.end, metrics=metrics
        )
        self.assertTrue(snapshot.requires_global_kill)
        with self.SessionLocal() as db:
            first = record_monitoring_snapshot(db, snapshot, idempotency_key="window-1")
            repeated = record_monitoring_snapshot(db, snapshot, idempotency_key="window-1")
            self.assertEqual(first.job_id, repeated.job_id)
            self.assertTrue(global_kill_active(db))
            self.assertTrue(first.payload_json["deterministic_scheduling_available"])
            self.assertEqual(2, db.query(SchedulingGovernanceJob).count())

        missing = healthy_metrics()
        missing.pop("hard_constraint_violations")
        outage = evaluate_monitoring_window(
            window_start=self.start, window_end=self.end, metrics=missing
        )
        self.assertTrue(outage.requires_global_kill)
        self.assertIn("monitoring_completeness", {
            item.key for item in outage.alerts if item.status == "firing"
        })


if __name__ == "__main__":
    unittest.main()
