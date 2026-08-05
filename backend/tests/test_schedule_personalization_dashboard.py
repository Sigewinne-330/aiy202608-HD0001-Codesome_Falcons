import sys
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import SchedulingModelPrediction, SchedulingOutcomeLabel  # noqa: E402
from services.schedule_personalization_config import PersonalizationRuntimeConfig  # noqa: E402
from services.schedule_personalization_dashboard import personalization_dashboard  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class PersonalizationDashboardTests(unittest.TestCase):
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
        with self.SessionLocal() as db:
            db.add(AppUser(username="dashboard", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            db.add(SchedulingModelPrediction(
                prediction_id="prediction-1", user_id=1, context_hash="a" * 64,
                prediction_type="effort", p50=60, p90=100, evidence_maturity=0.7,
                calibration_state="developing", feature_contributions={},
                learned_adjustment=0, serving_mode="shadow", latency_ms=10,
                eligibility_watermark=1,
            ))
            db.add(SchedulingOutcomeLabel(
                user_id=1, source_type="task", source_id=1, episode=1,
                derivation_version="labels.v1", outcome_cutoff_at=datetime(2026, 8, 5),
                active_minutes=90, planned_actual_ratio=1.5, terminal_state="completed",
                is_censored=False, label_confidence="high", eligible_personal=True,
                eligibility_watermark=1,
            ))
            db.commit()

    def test_projection_is_user_scoped_and_hides_sparse_calibration(self):
        with self.SessionLocal() as db:
            result = personalization_dashboard(
                db, 1, PersonalizationRuntimeConfig(master_enabled=True)
            )
        self.assertEqual(60.0, result["effort_range"]["p50_minutes"])
        self.assertEqual(100.0, result["effort_range"]["p90_minutes"])
        self.assertEqual(60.0, result["estimate_actual_trend"][0]["estimated_minutes"])
        self.assertFalse(result["calibration"]["visible"])
        self.assertFalse(result["contains_cross_user_detail"])
        self.assertFalse(result["contains_raw_task_text"])

    def test_watermark_reset_immediately_hides_old_projection(self):
        with self.SessionLocal() as db:
            consent = get_or_create_private_consent(db, 1)
            consent.eligibility_watermark = 2
            result = personalization_dashboard(db, 1, PersonalizationRuntimeConfig())
        self.assertIsNone(result["effort_range"]["p50_minutes"])
        self.assertEqual([], result["estimate_actual_trend"])


if __name__ == "__main__":
    unittest.main()
