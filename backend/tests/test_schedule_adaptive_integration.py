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
from models.scheduling import ScheduleIntervention  # noqa: E402
from models.schedule_personalization import SchedulingDecisionEvent  # noqa: E402
from models.task_new import Task, TaskType  # noqa: E402
from schemas.scheduling import InterventionResolveRequest, PreflightRequest, ScheduleDecision  # noqa: E402
from services.schedule_adaptive_integration import (  # noqa: E402
    RERANKER_ALGORITHM_VERSION,
    RERANKER_CALIBRATION_VERSION,
    RERANKER_FEATURE_VERSION,
    RERANKER_LABEL_VERSION,
)
from services.schedule_lifecycle import preflight_creation, resolve_intervention  # noqa: E402
from services.schedule_observation_hooks import capture_intervention_resolution_after_commit  # noqa: E402
from services.schedule_model_registry import (  # noqa: E402
    RegistryCompatibility,
    move_to_shadow,
    promote_model,
    register_candidate,
)
from services.schedule_personalization_config import PersonalizationRuntimeConfig  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class ScheduleAdaptiveIntegrationTests(unittest.TestCase):
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
        self.target = date.today() + timedelta(days=7)
        with self.SessionLocal() as db:
            db.add(AppUser(username="integration-user", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            for index in range(3):
                db.add(Task(
                    user_id=1,
                    task_type=TaskType.todo,
                    id_name=f"existing-{index}",
                    title=f"existing-{index}",
                    deadline=self.target,
                    estimated_hours=1,
                    status="todo",
                ))
            model = register_candidate(
                db,
                user_id=1,
                model_type="reranker",
                scope="personal",
                algorithm_version=RERANKER_ALGORITHM_VERSION,
                feature_schema_version=RERANKER_FEATURE_VERSION,
                label_version=RERANKER_LABEL_VERSION,
                calibration_version=RERANKER_CALIBRATION_VERSION,
                artifact_json={
                    "adjustment_by_baseline_rank": {"1": 0.2, "2": -0.2},
                    "maturity": 1,
                    "calibration_factor": 1,
                    "eligible_decision_count": 25,
                },
            )
            move_to_shadow(db, model.model_id)
            promote_model(
                db,
                model.model_id,
                approved_by="integration-gate",
                compatibility=RegistryCompatibility(
                    RERANKER_ALGORITHM_VERSION,
                    RERANKER_FEATURE_VERSION,
                    RERANKER_LABEL_VERSION,
                    RERANKER_CALIBRATION_VERSION,
                ),
            )
            db.commit()

    def _config(self, *, suggestion=False):
        return PersonalizationRuntimeConfig(
            master_enabled=True,
            modeling_enabled=True,
            shadow_enabled=not suggestion,
            suggestion_enabled=suggestion,
            ranking_decision_threshold=20,
            near_tie_score_delta=1,
            maximum_score_adjustment=0.25,
            maximum_rank_displacement=1,
        )

    def _exploration_config(self):
        return PersonalizationRuntimeConfig(
            master_enabled=True,
            modeling_enabled=True,
            suggestion_enabled=True,
            exploration_enabled=True,
            ranking_decision_threshold=20,
            near_tie_score_delta=1,
            maximum_score_adjustment=0.25,
            maximum_rank_displacement=1,
        )

    def test_shadow_annotations_follow_generation_but_persisted_authority_stays_baseline(self):
        with self.SessionLocal() as db:
            result = preflight_creation(
                db,
                1,
                PreflightRequest(
                    source_type="task",
                    title="new overload item",
                    target_date=self.target,
                    estimated_hours=1,
                ),
                personalization_config=self._config(),
            )
            baseline_dates = [result["recommendation"]["date"]] + [item["date"] for item in result["alternatives"]]
            personalization = result["personalization"]
            self.assertEqual("shadow", personalization["serving_mode"])
            self.assertEqual([f"date:{item}" for item in baseline_dates], personalization["baseline_order"])
            self.assertEqual(personalization["baseline_order"], personalization["display_order"])
            self.assertFalse(personalization["authority"]["learned_auto_apply"])

            row = db.query(ScheduleIntervention).filter_by(id=result["intervention_id"]).one()
            self.assertEqual(baseline_dates, [item["date"] for item in row.ranked_recommendations])

    def test_accept_recommendation_uses_persisted_deterministic_first_candidate(self):
        with self.SessionLocal() as db:
            preview = preflight_creation(
                db,
                1,
                PreflightRequest(
                    source_type="task",
                    title="automatic authority test",
                    target_date=self.target,
                    estimated_hours=1,
                ),
                personalization_config=self._config(suggestion=True),
            )
            deterministic_date = preview["recommendation"]["date"]
            resolved = resolve_intervention(
                db,
                1,
                preview["intervention_id"],
                InterventionResolveRequest(
                    decision=ScheduleDecision.accept_recommendation,
                    idempotency_key="adaptive-baseline-accept",
                ),
            )
            self.assertEqual(deterministic_date, resolved["date"])
            row = db.query(ScheduleIntervention).filter_by(id=preview["intervention_id"]).one()
            self.assertEqual(date.fromisoformat(deterministic_date), row.selected_date)

    def test_exploration_persists_display_metadata_without_reordering_apply_authority(self):
        with self.SessionLocal() as db:
            consent = get_or_create_private_consent(db, 1)
            consent.near_tie_exploration_enabled = True
            preview = preflight_creation(
                db,
                1,
                PreflightRequest(
                    source_type="task",
                    title="display-only experiment",
                    target_date=self.target,
                    estimated_hours=1,
                ),
                personalization_config=self._exploration_config(),
            )
            exploration = preview["personalization"]["exploration"]
            self.assertTrue(exploration["randomized"])
            self.assertGreater(exploration["assignment_probability"], 0)
            row = db.query(ScheduleIntervention).filter_by(id=preview["intervention_id"]).one()
            self.assertEqual(1, row.ranked_recommendations[0]["baseline_rank"])
            self.assertTrue(all(item["randomized_assignment"] for item in row.ranked_recommendations))
            self.assertEqual(
                preview["recommendation"]["date"],
                row.ranked_recommendations[0]["date"],
            )
            resolved = resolve_intervention(
                db,
                1,
                preview["intervention_id"],
                InterventionResolveRequest(
                    decision=ScheduleDecision.accept_recommendation,
                    idempotency_key="exploration-baseline-accept",
                ),
            )
            db.refresh(row)
            status = capture_intervention_resolution_after_commit(
                db,
                1,
                row,
                resolved["source_type"],
                resolved["id"],
                date.fromisoformat(resolved["date"]),
                ScheduleDecision.accept_recommendation.value,
                config=PersonalizationRuntimeConfig(
                    master_enabled=True,
                    observation_capture_enabled=True,
                ),
            )
            self.assertEqual("captured", status.state)
            event = db.query(SchedulingDecisionEvent).one()
            self.assertIsNotNone(event.action_propensity)
            self.assertAlmostEqual(exploration["assignment_probability"], float(event.action_propensity), places=7)
            self.assertEqual(
                {"numerator": 1, "denominator": exploration["assignment_denominator"]},
                event.context_snapshot["assignment_probability"],
            )
            expected_display = [
                f"date:{item['date']}"
                for item in sorted(row.ranked_recommendations, key=lambda item: item["display_rank"])
            ]
            self.assertEqual(expected_display, event.displayed_candidate_ids)


if __name__ == "__main__":
    unittest.main()
