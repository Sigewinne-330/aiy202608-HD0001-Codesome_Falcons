import sys
import unittest
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import SchedulingModelRegistry  # noqa: E402
from schemas.schedule_personalization import ModelType  # noqa: E402
from services.schedule_model_registry import (  # noqa: E402
    RegistryCompatibility,
    RegistryError,
    kill_model,
    move_to_shadow,
    promote_model,
    register_candidate,
    resolve_serving_model,
    validate_data_artifact,
)
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class ScheduleModelRegistryTests(unittest.TestCase):
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
            db.add(AppUser(username="registry-user", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            db.commit()
        self.compatibility = RegistryCompatibility(
            algorithm_version="effort.v1",
            feature_schema_version="features.v1",
            label_version="labels.v1",
            calibration_version="calibration.v1",
        )

    def _candidate(self, db, *, model_id=None, artifact=None, algorithm="effort.v1"):
        return register_candidate(
            db,
            model_id=model_id,
            user_id=1,
            model_type=ModelType.effort,
            scope="personal",
            algorithm_version=algorithm,
            feature_schema_version="features.v1",
            label_version="labels.v1",
            calibration_version="calibration.v1",
            source_eligibility_watermark=1,
            effective_sample_size=8,
            artifact_json=artifact or {"kind": "log_normal", "mean": 4.2, "sigma": 0.5},
            evaluation_metrics={"future_only": True, "coverage": 0.87},
            slice_metrics={"economics|essay_draft": {"n": 8}},
        )

    def _promote(self, db, candidate):
        move_to_shadow(db, candidate.model_id)
        return promote_model(
            db,
            candidate.model_id,
            approved_by="test-gate",
            compatibility=self.compatibility,
        )

    def test_artifact_rejects_executable_nonfinite_oversized_and_deep_values(self):
        invalid = (
            {"code": "print('unsafe')"},
            {"mean": float("inf")},
            {"opaque": object()},
            {"payload": "x" * 70_000},
        )
        for artifact in invalid:
            with self.subTest(artifact_type=next(iter(artifact))):
                with self.assertRaises(RegistryError):
                    validate_data_artifact(artifact)
        deep = current = {}
        for _ in range(14):
            current["next"] = {}
            current = current["next"]
        with self.assertRaises(RegistryError):
            validate_data_artifact(deep)

    def test_candidate_is_idempotent_by_uuid_but_immutable_on_conflict(self):
        stable_id = str(uuid4())
        artifact = {"kind": "log_normal", "mean": 4.2}
        with self.SessionLocal() as db:
            first = self._candidate(db, model_id=stable_id, artifact=artifact)
            artifact["mean"] = 999
            self.assertEqual(4.2, first.artifact_json["mean"])
            repeated = self._candidate(db, model_id=stable_id, artifact={"kind": "log_normal", "mean": 4.2})
            self.assertEqual(first.id, repeated.id)
            with self.assertRaises(RegistryError):
                self._candidate(db, model_id=stable_id, artifact={"kind": "log_normal", "mean": 5.0})

    def test_promotion_supersedes_atomically_and_kill_rolls_back(self):
        with self.SessionLocal() as db:
            first = self._promote(db, self._candidate(db))
            db.commit()
            second = self._promote(db, self._candidate(db, artifact={"kind": "log_normal", "mean": 4.5}))
            db.commit()
            db.refresh(first)
            self.assertEqual("superseded", first.lifecycle)
            self.assertEqual(first.id, second.fallback_model_id)

            resolution = kill_model(
                db,
                second.model_id,
                reason="calibration_incident",
                compatibility=self.compatibility,
            )
            db.commit()
            self.assertEqual("rolled_back", resolution.fallback_reason)
            self.assertEqual(first.id, resolution.model.id)
            self.assertEqual("promoted", resolution.model.lifecycle)
            self.assertEqual("killed", second.lifecycle)

            serving = resolve_serving_model(
                db,
                user_id=1,
                model_type=ModelType.effort,
                scope="personal",
                compatibility=self.compatibility,
            )
            self.assertEqual(first.id, serving.model.id)

    def test_failed_promotion_keeps_previous_model_serving(self):
        with self.SessionLocal() as db:
            previous = self._promote(db, self._candidate(db))
            db.commit()
            candidate = self._candidate(db, artifact={"kind": "log_normal", "mean": 4.8})
            move_to_shadow(db, candidate.model_id)
            db.flush()

            def fail_update():
                raise RuntimeError("injected registry write failure")

            with self.assertRaises(RuntimeError):
                promote_model(
                    db,
                    candidate.model_id,
                    approved_by="test-gate",
                    compatibility=self.compatibility,
                    failure_injector=fail_update,
                )
            db.expire_all()
            still_serving = db.query(SchedulingModelRegistry).filter_by(id=previous.id).one()
            failed = db.query(SchedulingModelRegistry).filter_by(id=candidate.id).one()
            self.assertEqual("promoted", still_serving.lifecycle)
            self.assertEqual("shadow", failed.lifecycle)
            self.assertIsNone(failed.fallback_model_id)

    def test_mixed_versions_fail_closed_and_incompatible_history_is_not_rollback(self):
        with self.SessionLocal() as db:
            old = self._promote(db, self._candidate(db))
            db.commit()
            incompatible = RegistryCompatibility(
                algorithm_version="effort.v2",
                feature_schema_version="features.v2",
                label_version="labels.v1",
                calibration_version="calibration.v1",
            )
            resolution = resolve_serving_model(
                db,
                user_id=1,
                model_type="effort",
                scope="personal",
                compatibility=incompatible,
            )
            self.assertIsNone(resolution.model)
            self.assertEqual("no_compatible_promoted_model", resolution.fallback_reason)

            killed = kill_model(
                db,
                old.model_id,
                reason="mixed_application_version",
                compatibility=incompatible,
            )
            self.assertIsNone(killed.model)
            self.assertEqual("prior_fallback", killed.fallback_reason)

    def test_withdrawal_watermark_excludes_previously_promoted_model(self):
        with self.SessionLocal() as db:
            self._promote(db, self._candidate(db))
            consent = get_or_create_private_consent(db, 1)
            consent.eligibility_watermark = 2
            db.flush()
            resolution = resolve_serving_model(
                db,
                user_id=1,
                model_type="effort",
                scope="personal",
                compatibility=self.compatibility,
            )
            self.assertIsNone(resolution.model)
            self.assertEqual("no_compatible_promoted_model", resolution.fallback_reason)


if __name__ == "__main__":
    unittest.main()
