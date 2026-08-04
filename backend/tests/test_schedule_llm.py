import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base  # noqa: E402
import models  # noqa: F401,E402
from models.app_user import AppUser  # noqa: E402
from models.reminder import LLMUsageRecord  # noqa: E402
from services.ai_service import LLMCompletionResult  # noqa: E402
from services.llm_usage import LLMQuotaPolicy  # noqa: E402
from services.schedule_llm import estimate_effort, explain_recommendation  # noqa: E402


class ScheduleLlmBoundaryTests(unittest.IsolatedAsyncioTestCase):
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
            db.add(AppUser(username="llm-scheduler", password="x", balance=10000))
            db.commit()

    async def test_provider_usage_is_recorded_and_result_is_bounded(self):
        completion = LLMCompletionResult(
            content='{"estimated_hours": 30, "confidence": 1.2}',
            provider="test",
            model="test-model",
            finish_reason="stop",
            tool_calls=[],
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        )
        with patch("services.schedule_llm.ai_service.complete_once", new=AsyncMock(return_value=completion)):
            with self.SessionLocal() as db:
                estimate = await estimate_effort(db, 1, "long task", "details")
                self.assertEqual("llm", estimate.source)
                self.assertEqual(24.0, estimate.estimated_hours)
                self.assertEqual(1.0, estimate.confidence)
                usage = db.query(LLMUsageRecord).filter_by(purpose="schedule_effort_estimation").one()
                self.assertEqual(15, usage.total_tokens)

    async def test_provider_failure_falls_back_without_fake_usage(self):
        with patch("services.schedule_llm.ai_service.complete_once", new=AsyncMock(side_effect=RuntimeError("offline"))):
            with self.SessionLocal() as db:
                estimate = await estimate_effort(db, 1, "vague task")
                self.assertEqual("default", estimate.source)
                self.assertEqual(1.0, estimate.estimated_hours)
                self.assertEqual(0, db.query(LLMUsageRecord).count())

    async def test_explanation_uses_structured_facts_and_records_usage(self):
        completion = LLMCompletionResult(
            content="建议安排在 2026-08-08，投入约 1.5 小时。",
            provider="test",
            model="test-model",
            finish_reason="stop",
            tool_calls=[],
            prompt_tokens=12,
            completion_tokens=8,
            total_tokens=20,
        )
        recommendation = {
            "date": "2026-08-08",
            "recommended_effort_hours": 1.5,
            "energy_ratio": 0.75,
            "increase_effort": False,
            "reason_codes": ["balanced_capacity"],
            "description": "must not be forwarded",
            "api_key": "must not be forwarded",
        }
        with patch("services.schedule_llm.ai_service.complete_once", new=AsyncMock(return_value=completion)) as mocked:
            with self.SessionLocal() as db:
                explanation = await explain_recommendation(db, 1, recommendation, language="zh-CN")
                self.assertEqual("llm", explanation.source)
                self.assertEqual(20, explanation.total_tokens)
                usage = db.query(LLMUsageRecord).filter_by(purpose="schedule_explanation").one()
                self.assertEqual(20, usage.total_tokens)
                sent = mocked.await_args.args[0][1]["content"]
                self.assertNotIn("must not be forwarded", sent)

    async def test_explanation_has_localized_template_without_provider_or_quota(self):
        recommendation = {
            "date": "2026-08-09",
            "recommended_effort_hours": 2,
            "energy_ratio": 0.8,
            "increase_effort": True,
        }
        with self.SessionLocal() as db:
            policy = LLMQuotaPolicy(monthly_limit=1)
            with patch.object(policy, "allows_generation", return_value=False):
                explanation = await explain_recommendation(
                    db,
                    1,
                    recommendation,
                    language="zh-CN",
                    quota_policy=policy,
                )
            self.assertEqual("template", explanation.source)
            self.assertIn("2026-08-09", explanation.text)
            self.assertIn("2", explanation.text)
            self.assertEqual(0, db.query(LLMUsageRecord).count())


if __name__ == "__main__":
    unittest.main()
