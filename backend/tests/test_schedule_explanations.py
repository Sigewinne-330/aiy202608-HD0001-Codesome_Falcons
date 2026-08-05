import asyncio
import sys
import unittest
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
from services.schedule_explanations import build_structured_explanation, project_explanation  # noqa: E402
from services.schedule_personalization_governance import get_or_create_private_consent  # noqa: E402


class ScheduleExplanationTests(unittest.TestCase):
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
            db.add(AppUser(username="explanation-user", password="x", balance=10000))
            db.flush()
            consent = get_or_create_private_consent(db, 1)
            consent.operational_personalization_enabled = True
            consent.llm_memory_enabled = True
            db.commit()
        self.recommendation = {
            "date": "2026-08-10",
            "score": 1.2,
            "reason_codes": ["within_capacity", "before_hard_deadline"],
            "baseline_rank": 2,
        }
        self.personalization = {
            "serving_mode": "suggestion",
            "model_version": "model-v1",
            "baseline_order": ["date:2026-08-09", "date:2026-08-10"],
            "display_order": ["date:2026-08-10", "date:2026-08-09"],
            "annotations": [{
                "candidate_id": "date:2026-08-10",
                "baseline_rank": 2,
                "personalized_rank": 1,
                "learned_adjustment": -0.1,
                "estimate_p50_minutes": 120,
                "estimate_p90_minutes": 190,
                "maturity": 0.8,
                "calibration_factor": 0.85,
                "evidence_categories": [
                    "eligible_decision_history",
                    "cross_user_secret",
                    "psychological_trait",
                ],
            }],
        }

    def test_structured_explanation_separates_authority_evidence_and_uncertainty(self):
        value = build_structured_explanation(self.recommendation, self.personalization)
        self.assertEqual("feasibility_and_apply", value["deterministic"]["authority"])
        self.assertEqual(2, value["personalization"]["baseline_rank"])
        self.assertEqual(1, value["personalization"]["personalized_rank"])
        self.assertFalse(value["personalization"]["can_auto_apply"])
        self.assertEqual(120, value["estimate_range"]["p50_minutes"])
        self.assertEqual(190, value["estimate_range"]["p90_minutes"])
        self.assertEqual(["eligible_decision_history"], value["personalization"]["evidence_categories"])
        self.assertFalse(value["uncertainty"]["causal_claim"])
        self.assertFalse(value["uncertainty"]["psychological_trait_inference"])

    def test_provider_failure_uses_bounded_deterministic_wording(self):
        async def malformed(_messages, _max_tokens):
            return "not-json"

        with self.SessionLocal() as db:
            result = asyncio.run(project_explanation(
                db,
                1,
                current_task={"title": "Essay", "subject": "Economics"},
                recommendation=self.recommendation,
                personalization=self.personalization,
                provider=malformed,
            ))
        self.assertFalse(result.used_provider)
        self.assertEqual("malformed_provider_output", result.fallback_reason)
        self.assertEqual("2026-08-10", result.structured["deterministic"]["date"])
        self.assertIn("summary", result.wording)
        self.assertEqual("explanation", result.audit["purpose"])


if __name__ == "__main__":
    unittest.main()
