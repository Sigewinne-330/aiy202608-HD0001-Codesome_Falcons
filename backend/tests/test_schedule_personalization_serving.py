import sys
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.schedule_personalization import SchedulingModelPrediction  # noqa: E402
from services.schedule_adaptive_ranking import LearnedCandidateSignal, SafeCandidateSnapshot  # noqa: E402
from services.schedule_model_registry import (  # noqa: E402
    RegistryCompatibility,
    move_to_shadow,
    promote_model,
    register_candidate,
)
from services.schedule_personalization_config import PersonalizationRuntimeConfig  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402
from services.schedule_personalization_serving import serve_personalization  # noqa: E402


class SchedulePersonalizationServingTests(unittest.TestCase):
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
            db.add(AppUser(username="serving-user", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            db.commit()
        self.candidates = tuple(SafeCandidateSnapshot(
            candidate_id=f"date:{(date(2026, 8, 5) + timedelta(days=index)).isoformat()}",
            local_date=date(2026, 8, 5) + timedelta(days=index),
            deterministic_score=float(index),
            baseline_rank=index,
            reason_codes=("capacity_safe",),
            hard_constraint_proof=("deadline", "capacity"),
            effort_minutes=60,
        ) for index in (1, 2))

    def _model(self, db, *, promoted=True):
        row = register_candidate(
            db,
            user_id=1,
            model_type="reranker",
            scope="personal",
            algorithm_version="reranker.v1",
            feature_schema_version="features.v1",
            label_version="labels.v1",
            calibration_version="calibration.v1",
            artifact_json={"kind": "linear", "coefficients": {"slack": 0.1}},
        )
        if promoted:
            move_to_shadow(db, row.model_id)
            promote_model(
                db,
                row.model_id,
                approved_by="test-gate",
                compatibility=RegistryCompatibility(
                    "reranker.v1", "features.v1", "labels.v1", "calibration.v1"
                ),
            )
        return row

    @staticmethod
    def _predict(candidates):
        return tuple(LearnedCandidateSignal(
            candidate_id=item.candidate_id,
            raw_adjustment=-0.1,
            model_version="reranker.v1",
            maturity=0.9,
            calibration_factor=0.9,
            eligible_decision_count=25,
            evidence_categories=("eligible_decisions",),
            completion_probability=0.8,
        ) for item in candidates)

    def _config(self, mode):
        return PersonalizationRuntimeConfig(
            master_enabled=mode != "disabled",
            modeling_enabled=mode != "disabled",
            shadow_enabled=mode == "shadow",
            suggestion_enabled=mode == "suggestion",
            kill_switch=mode == "killed",
            inference_latency_budget_ms=10,
        )

    def test_serving_state_matrix_preserves_baseline_until_bounded_policy(self):
        with self.SessionLocal() as db:
            model = self._model(db)
            db.commit()
            for mode in ("disabled", "replay", "shadow", "suggestion", "killed"):
                called = []

                def predictor(candidates):
                    called.append(True)
                    return self._predict(candidates)

                result = serve_personalization(
                    db,
                    user_id=1,
                    candidates=self.candidates,
                    predictor=predictor,
                    model=model,
                    context_identity=f"matrix:{mode}",
                    config=self._config(mode),
                )
                self.assertEqual(mode, result.mode.value)
                self.assertEqual(result.ranking.baseline_order, result.ranking.display_order)
                self.assertEqual(mode not in {"disabled", "killed"}, bool(called))
                expected_logs = 0 if mode in {"disabled", "killed"} else len(self.candidates)
                self.assertEqual(expected_logs, result.prediction_count)

    def test_timeout_returns_prompt_zero_adjustment_and_logs_fallback(self):
        with self.SessionLocal() as db:
            model = self._model(db)
            db.commit()

            def slow(_candidates):
                time.sleep(0.15)
                return ()

            started = time.monotonic()
            result = serve_personalization(
                db,
                user_id=1,
                candidates=self.candidates,
                predictor=slow,
                model=model,
                context_identity="timeout",
                config=self._config("shadow"),
            )
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.10)
            self.assertTrue(result.timed_out)
            self.assertEqual("inference_timeout", result.fallback_reason)
            self.assertTrue(all(item.applied_adjustment == 0 for item in result.ranking.annotations))
            rows = db.query(SchedulingModelPrediction).all()
            self.assertEqual(2, len(rows))
            self.assertTrue(all(row.feature_contributions["fallback_reason"] == "inference_timeout" for row in rows))

    def test_corruption_ineligible_model_and_consent_disable_fail_closed(self):
        with self.SessionLocal() as db:
            candidate_model = self._model(db, promoted=False)
            ineligible = serve_personalization(
                db,
                user_id=1,
                candidates=self.candidates,
                predictor=self._predict,
                model=candidate_model,
                context_identity="ineligible",
                config=self._config("shadow"),
            )
            self.assertEqual("model_ineligible", ineligible.fallback_reason)

            promoted = self._model(db)
            corrupt = serve_personalization(
                db,
                user_id=1,
                candidates=self.candidates,
                predictor=lambda _items: ({"not": "a signal"},),
                model=promoted,
                context_identity="corrupt",
                config=self._config("shadow"),
            )
            self.assertEqual("corrupt_prediction", corrupt.fallback_reason)

            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = False
            disabled = serve_personalization(
                db,
                user_id=1,
                candidates=self.candidates,
                predictor=self._predict,
                model=promoted,
                context_identity="consent",
                config=self._config("shadow"),
            )
            self.assertEqual("consent_disabled", disabled.fallback_reason)
            self.assertEqual(0, disabled.prediction_count)

    def test_prediction_logging_failure_does_not_break_deterministic_result(self):
        with self.SessionLocal() as db:
            model = self._model(db)
            db.commit()
            def reject_prediction_log(session, _flush_context, _instances):
                if any(isinstance(item, SchedulingModelPrediction) for item in session.new):
                    raise RuntimeError("injected prediction log outage")

            event.listen(db, "before_flush", reject_prediction_log)
            try:
                result = serve_personalization(
                    db,
                    user_id=1,
                    candidates=self.candidates,
                    predictor=self._predict,
                    model=model,
                    context_identity="logging-outage",
                    config=self._config("shadow"),
                )
            finally:
                event.remove(db, "before_flush", reject_prediction_log)
            self.assertEqual(result.ranking.baseline_order, result.ranking.display_order)
            self.assertEqual("prediction_logging_failed", result.fallback_reason)
            self.assertEqual(0, result.prediction_count)


if __name__ == "__main__":
    unittest.main()
