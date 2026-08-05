import math
import sys
import unittest
from datetime import date, timedelta
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
from models.schedule_personalization import SchedulingFeatureSnapshot  # noqa: E402
from services.schedule_effort_model import EffortModelPolicy, predict_effort_distribution  # noqa: E402
from services.schedule_features import SUFFICIENT_STATISTICS_VERSION  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_taxonomy import resolve_effort_prior  # noqa: E402


class ScheduleEffortModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.SessionLocal() as db:
            db.add(AppUser(username="effort-model", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            db.commit()
        self.reference = date(2026, 8, 5)

    def _snapshot(self, db, n, mean_minutes, *, latest=None, variance=0.08):
        row = SchedulingFeatureSnapshot(
            user_id=1,
            scope_type="user_segment",
            scope_key="economics|essay_draft",
            reference_date=self.reference,
            window_start=self.reference - timedelta(days=364),
            window_end=self.reference,
            feature_schema_version=SUFFICIENT_STATISTICS_VERSION,
            source_eligibility_watermark=1,
            effective_sample_size=n,
            sufficient_statistics={
                "effective_sample_size": n,
                "mean_log_minutes": math.log(mean_minutes),
                "variance_log_minutes": variance,
                "latest_outcome_date": (latest or self.reference).isoformat(),
                "source_label_hash": f"hash-{n}-{mean_minutes}-{latest}",
            },
            recent_statistics={},
            recency_policy={},
            drift_state="stable",
            eligible_cross_user=False,
        )
        db.add(row)
        db.flush()
        return row

    def test_cold_start_returns_versioned_ib_prior_distribution(self):
        with self.SessionLocal() as db:
            prediction = predict_effort_distribution(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=self.reference
            )
        prior = resolve_effort_prior(task_archetype="essay_draft", subject="Economics")
        self.assertEqual(prior.p50_active_minutes, prediction.p50_active_minutes)
        self.assertEqual("ib_prior", prediction.prior_level)
        self.assertEqual("cold_start", prediction.maturity_state)
        self.assertEqual("prior_only", prediction.calibration_state)
        self.assertEqual("no_personal_evidence", prediction.fallback_reason)
        self.assertLess(prediction.p10_active_minutes, prediction.p50_active_minutes)
        self.assertLess(prediction.p50_active_minutes, prediction.p90_active_minutes)

    def test_five_observation_gate_and_shrinkage_correct_repeated_underestimation(self):
        prior = resolve_effort_prior(task_archetype="essay_draft", subject="Economics")
        with self.SessionLocal() as db:
            row = self._snapshot(db, 4, 420)
            sparse = predict_effort_distribution(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=self.reference
            )
            self.assertFalse(sparse.correction_gate_passed)
            self.assertEqual(prior.p50_active_minutes, sparse.p50_active_minutes)
            self.assertEqual("warming_up", sparse.maturity_state)

            row.effective_sample_size = 5
            row.sufficient_statistics = {
                **row.sufficient_statistics,
                "effective_sample_size": 5,
                "source_label_hash": "five-comparable",
            }
            db.flush()
            corrected = predict_effort_distribution(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=self.reference
            )
            repeated = predict_effort_distribution(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=self.reference
            )
        self.assertTrue(corrected.correction_gate_passed)
        self.assertEqual("user_segment", corrected.selected_personal_level)
        self.assertGreater(corrected.p50_active_minutes, prior.p50_active_minutes)
        self.assertLess(corrected.p50_active_minutes, 420)
        self.assertGreater(corrected.personal_weight, 0)
        self.assertEqual(corrected.to_dict(), repeated.to_dict())

    def test_gate_is_configurable_but_influence_remains_bounded(self):
        with self.SessionLocal() as db:
            self._snapshot(db, 4, 600)
            prediction = predict_effort_distribution(
                db,
                1,
                subject="Economics",
                task_archetype="essay_draft",
                reference_date=self.reference,
                policy=EffortModelPolicy(correction_gate_effective_n=3),
            )
        self.assertTrue(prediction.correction_gate_passed)
        self.assertLessEqual(prediction.personal_weight, 0.8)
        self.assertLess(prediction.p50_active_minutes, 600)

    def test_stale_personal_evidence_falls_back_to_prior_with_freshness(self):
        prior = resolve_effort_prior(task_archetype="essay_draft", subject="Economics")
        with self.SessionLocal() as db:
            self._snapshot(db, 20, 500, latest=self.reference - timedelta(days=200))
            prediction = predict_effort_distribution(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=self.reference
            )
        self.assertFalse(prediction.correction_gate_passed)
        self.assertEqual(prior.p50_active_minutes, prediction.p50_active_minutes)
        self.assertEqual("stale", prediction.freshness_state)
        self.assertEqual(200, prediction.days_since_evidence)
        self.assertEqual("personal_evidence_stale", prediction.fallback_reason)

    def test_corrupt_or_extreme_statistics_cannot_produce_unbounded_intervals(self):
        with self.SessionLocal() as db:
            row = self._snapshot(db, 10, 1_000_000_000, variance=-1)
            invalid = predict_effort_distribution(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=self.reference
            )
            self.assertFalse(invalid.correction_gate_passed)
            self.assertEqual("invalid_personal_statistics", invalid.fallback_reason)

            row.sufficient_statistics = {**row.sufficient_statistics, "variance_log_minutes": 1000}
            db.flush()
            bounded = predict_effort_distribution(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=self.reference
            )
        self.assertTrue(bounded.correction_gate_passed)
        self.assertTrue(math.isfinite(bounded.mean_log_minutes))
        self.assertLessEqual(bounded.p90_active_minutes, 10_080)
        self.assertLessEqual(bounded.log_sigma, 1.5)

    def test_policy_bounds(self):
        with self.assertRaises(ValueError):
            EffortModelPolicy(correction_gate_effective_n=0).validate()
        with self.assertRaises(ValueError):
            EffortModelPolicy(user_global_maximum_weight=0.9).validate()


if __name__ == "__main__":
    unittest.main()
