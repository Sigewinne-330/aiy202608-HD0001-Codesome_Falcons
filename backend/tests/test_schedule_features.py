import math
import sys
import unittest
from datetime import date, datetime, timedelta
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
from models.schedule_personalization import SchedulingFeatureSnapshot, SchedulingOutcomeLabel  # noqa: E402
from models.task_new import Task  # noqa: E402
from services.schedule_features import (  # noqa: E402
    FeatureDerivationPolicy,
    derive_sufficient_statistics,
    resolve_feature_hierarchy,
)
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class ScheduleFeatureTests(unittest.TestCase):
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
            db.add(AppUser(username="features", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            consent.raw_event_retention_days = 365
            db.commit()

    def _task(self, db, title, subject, archetype):
        row = Task(
            user_id=1,
            title=title,
            subject=subject,
            schedule_kind=archetype,
            status="done",
        )
        db.add(row)
        db.flush()
        return row

    def _label(
        self,
        db,
        task,
        reference_date,
        minutes,
        *,
        days_ago=0,
        provenance="active_timer_measured",
        confidence="high",
        complete=True,
        watermark=1,
        eligible=True,
    ):
        row = SchedulingOutcomeLabel(
            user_id=1,
            source_type="task",
            source_id=task.id,
            episode=1,
            derivation_version=f"fixture-{task.id}-{days_ago}-{minutes}",
            outcome_cutoff_at=datetime.combine(reference_date - timedelta(days=days_ago), datetime.min.time()),
            active_minutes=minutes,
            active_minutes_provenance=provenance,
            interval_complete=complete,
            terminal_state="completed",
            is_censored=False,
            label_confidence=confidence,
            eligible_personal=eligible,
            eligible_evaluation=True,
            eligible_cross_user=False,
            eligibility_watermark=watermark,
        )
        db.add(row)
        db.flush()
        return row

    def test_deterministic_weighted_long_recent_statistics_and_scopes(self):
        reference = date(2026, 8, 5)
        with self.SessionLocal() as db:
            first = self._task(db, "Economics essay", "Economics", "essay_draft")
            second = self._task(db, "Economics essay 2", "经济学", "essay_draft")
            self._label(db, first, reference, 120, days_ago=2)
            self._label(
                db,
                second,
                reference,
                240,
                days_ago=60,
                provenance="user_reported_proxy",
                confidence="medium",
                complete=False,
            )
            rows = derive_sufficient_statistics(db, 1, reference_date=reference)
            snapshots = {(row.scope_type, row.scope_key): row for row in rows}
            self.assertIn(("user_global", "all"), snapshots)
            self.assertIn(("user_subject", "economics"), snapshots)
            self.assertIn(("user_archetype", "essay_draft"), snapshots)
            self.assertIn(("user_segment", "economics|essay_draft"), snapshots)
            segment = snapshots[("user_segment", "economics|essay_draft")]
            self.assertEqual(2, segment.sufficient_statistics["raw_count"])
            self.assertEqual(1, segment.recent_statistics["raw_count"])
            self.assertLess(float(segment.effective_sample_size), 2)
            first_dump = dict(segment.sufficient_statistics)
            repeated = derive_sufficient_statistics(db, 1, reference_date=reference)
            repeated_segment = next(row for row in repeated if row.scope_type == "user_segment")
            self.assertEqual(segment.id, repeated_segment.id)
            self.assertEqual(first_dump, repeated_segment.sufficient_statistics)

    def test_consent_watermark_retention_and_missing_effort_exclusion(self):
        reference = date(2026, 8, 5)
        with self.SessionLocal() as db:
            consent = get_or_create_private_consent(db, 1)
            consent.raw_event_retention_days = 30
            task = self._task(db, "Physics lab", "Physics", "laboratory")
            self._label(db, task, reference, 60, days_ago=5)
            self._label(db, task, reference, 90, days_ago=40)
            self._label(db, task, reference, 120, days_ago=3, watermark=99)
            self._label(db, task, reference, 0, days_ago=2)
            self._label(db, task, reference, 45, days_ago=1, eligible=False)
            rows = derive_sufficient_statistics(db, 1, reference_date=reference)
            global_row = next(row for row in rows if row.scope_type == "user_global")
            self.assertEqual(1, global_row.sufficient_statistics["raw_count"])
            excluded = global_row.sufficient_statistics["excluded_counts"]
            self.assertEqual(1, excluded["retention_or_window"])
            self.assertEqual(1, excluded["watermark_mismatch"])
            self.assertEqual(1, excluded["missing_effort"])
            self.assertEqual(1, excluded["not_personal_eligible"])

            consent.operational_personalization_enabled = False
            self.assertEqual((), derive_sufficient_statistics(db, 1, reference_date=reference + timedelta(days=1)))

    def test_outlier_caps_make_statistics_finite_and_bounded(self):
        reference = date(2026, 8, 5)
        with self.SessionLocal() as db:
            task = self._task(db, "Unknown build", None, "unknown")
            self._label(db, task, reference, 1_000_000)
            row = next(
                value for value in derive_sufficient_statistics(db, 1, reference_date=reference)
                if value.scope_type == "user_global"
            )
            stats = row.sufficient_statistics
            self.assertEqual(1, stats["capped_count"])
            self.assertLessEqual(stats["maximum_bounded_minutes"], 1_440)
            self.assertTrue(math.isfinite(stats["mean_log_minutes"]))
            self.assertTrue(math.isfinite(stats["variance_log_minutes"]))
            self.assertLessEqual(float(row.effective_sample_size), 1)

    def test_hierarchy_falls_back_segment_to_user_to_ib_to_global(self):
        reference = date(2026, 8, 5)
        with self.SessionLocal() as db:
            task = self._task(db, "Economics essay", "Economics", "essay_draft")
            self._label(db, task, reference, 180)
            derive_sufficient_statistics(db, 1, reference_date=reference)

            segment = resolve_feature_hierarchy(
                db, 1, subject="Economics", task_archetype="essay_draft", reference_date=reference
            )
            self.assertEqual("user_segment", segment.selected.level)
            self.assertEqual("global_prior", segment.specific_to_broad[-1].level)
            self.assertIn("ib_prior", [item.level for item in segment.specific_to_broad])
            self.assertEqual(tuple(reversed(segment.specific_to_broad)), segment.broad_to_specific)

            ib = resolve_feature_hierarchy(
                db, 1, subject="Physics", task_archetype="laboratory", reference_date=reference
            )
            self.assertEqual("user_global", ib.selected.level)
            self.assertIn("ib_prior", [item.level for item in ib.specific_to_broad])

            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = False
            general = resolve_feature_hierarchy(
                db, 1, subject="Robotics", task_archetype="unknown", reference_date=reference
            )
            self.assertEqual("global_prior", general.selected.level)
            self.assertEqual(1, len(general.specific_to_broad))

    def test_policy_numerical_bounds(self):
        with self.assertRaises(ValueError):
            FeatureDerivationPolicy(recent_window_days=500).validate()
        with self.assertRaises(ValueError):
            FeatureDerivationPolicy(maximum_event_weight=2).validate()


if __name__ == "__main__":
    unittest.main()
