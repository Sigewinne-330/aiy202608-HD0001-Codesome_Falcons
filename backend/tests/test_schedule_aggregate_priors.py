import math
import os
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
from models.schedule_personalization import SchedulingFeatureSnapshot, SchedulingGovernanceJob  # noqa: E402
from schemas.schedule_personalization import GovernanceJobStatus  # noqa: E402
from services.schedule_aggregate_priors import materialize_aggregate_priors, resolve_aggregate_prior  # noqa: E402
from services.schedule_features import SUFFICIENT_STATISTICS_VERSION  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_personalization_jobs import DEFAULT_JOB_HANDLERS  # noqa: E402


class ScheduleAggregatePriorTests(unittest.TestCase):
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
        self.reference = date(2026, 8, 5)
        with self.SessionLocal() as db:
            for index in range(1, 5):
                db.add(AppUser(username=f"aggregate-{index}", password="x", balance=10000))
            db.flush()
            for user_id in range(1, 5):
                consent = get_or_create_private_consent(db, user_id)
                consent.operational_personalization_enabled = True
                consent.cross_user_learning_enabled = user_id <= 3
                db.add(SchedulingFeatureSnapshot(
                    user_id=user_id,
                    scope_type="user_segment",
                    scope_key="Economics|essay_draft",
                    reference_date=self.reference,
                    window_start=self.reference - timedelta(days=30),
                    window_end=self.reference,
                    feature_schema_version=SUFFICIENT_STATISTICS_VERSION,
                    source_eligibility_watermark=1,
                    effective_sample_size=5,
                    sufficient_statistics={
                        "effective_sample_size": 5,
                        "mean_log_minutes": math.log(100 + user_id * 10),
                        "variance_log_minutes": 0.2,
                        "forbidden_title": f"private-user-{user_id}",
                    },
                    recent_statistics={},
                    recency_policy={},
                    drift_state="stable",
                    eligible_cross_user=True,
                ))
            db.commit()

    def test_only_opted_in_structured_contributions_form_sufficient_cell(self):
        with self.SessionLocal() as db:
            snapshot = materialize_aggregate_priors(
                db, reference_date=self.reference, enabled=True, minimum_cell_contributors=3
            )
        payload = snapshot.to_dict()
        self.assertFalse(payload["contains_direct_identifiers"])
        self.assertFalse(payload["contains_raw_text"])
        self.assertNotIn("private-user", str(payload))
        cell = snapshot.cells[0]
        self.assertEqual(3, cell.contributor_count)
        self.assertTrue(cell.sufficient)
        resolved = resolve_aggregate_prior(
            snapshot, subject="Economics", task_archetype="essay_draft"
        )
        self.assertEqual("cross_user_aggregate", resolved.source)
        self.assertEqual(3, resolved.contributor_count)

    def test_small_cell_collapses_to_versioned_product_prior(self):
        with self.SessionLocal() as db:
            snapshot = materialize_aggregate_priors(
                db, reference_date=self.reference, enabled=True, minimum_cell_contributors=4
            )
        resolved = resolve_aggregate_prior(
            snapshot, subject="Economics", task_archetype="essay_draft"
        )
        self.assertEqual("versioned_product_prior", resolved.source)
        self.assertEqual(0, resolved.contributor_count)

    def test_withdrawal_recomputation_excludes_contribution_and_changes_version(self):
        with self.SessionLocal() as db:
            before = materialize_aggregate_priors(
                db, reference_date=self.reference, enabled=True, minimum_cell_contributors=2
            )
            consent = get_or_create_private_consent(db, 1)
            consent.cross_user_learning_enabled = False
            db.query(SchedulingFeatureSnapshot).filter_by(user_id=1).update({
                SchedulingFeatureSnapshot.eligible_cross_user: False
            }, synchronize_session=False)
            after = materialize_aggregate_priors(
                db, reference_date=self.reference, enabled=True, minimum_cell_contributors=2
            )
        self.assertNotEqual(before.aggregate_version, after.aggregate_version)
        self.assertEqual(2, after.cells[0].contributor_count)

    def test_global_runtime_disable_produces_no_cross_user_cells(self):
        with self.SessionLocal() as db:
            snapshot = materialize_aggregate_priors(
                db, reference_date=self.reference, enabled=False, minimum_cell_contributors=2
            )
        self.assertEqual((), snapshot.cells)

    def test_recompute_job_honors_runtime_switch_and_returns_bounded_lineage(self):
        with self.SessionLocal() as db:
            job = SchedulingGovernanceJob(
                job_id="aggregate-job",
                idempotency_key="aggregate-job",
                user_id=1,
                job_type="recompute_aggregate",
                status=GovernanceJobStatus.pending.value,
                payload_json={
                    "reference_date": self.reference.isoformat(),
                    "minimum_cell_contributors": 2,
                },
            )
            db.add(job)
            db.flush()
            old = {key: os.environ.get(key) for key in (
                "SCHEDULING_PERSONALIZATION_ENABLED",
                "SCHEDULING_CROSS_USER_AGGREGATION_ENABLED",
            )}
            try:
                os.environ["SCHEDULING_PERSONALIZATION_ENABLED"] = "true"
                os.environ["SCHEDULING_CROSS_USER_AGGREGATION_ENABLED"] = "true"
                enabled = DEFAULT_JOB_HANDLERS["recompute_aggregate"](db, job)
                os.environ["SCHEDULING_CROSS_USER_AGGREGATION_ENABLED"] = "false"
                disabled = DEFAULT_JOB_HANDLERS["recompute_aggregate"](db, job)
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        self.assertTrue(enabled["runtime_enabled"])
        self.assertEqual(1, len(enabled["cells"]))
        self.assertFalse(disabled["runtime_enabled"])
        self.assertEqual([], disabled["cells"])
        self.assertFalse(enabled["contains_direct_identifiers"])
        self.assertNotEqual(enabled["aggregate_version"], disabled["aggregate_version"])


if __name__ == "__main__":
    unittest.main()
