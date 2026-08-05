import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from schemas.schedule_personalization import (  # noqa: E402
    ConsentSettingsUpdate,
    DecisionCandidateContract,
    DecisionObservationInput,
    EvidenceConfidence,
    EvidenceProvenance,
    MemoryEntryInput,
    MemoryTier,
    ModelArtifactContract,
    ModelType,
    ServingMode,
    SourceReference,
    TaskArchetype,
    TaskArchetypeHypothesis,
    WorkEventInput,
    WorkEventType,
)
from services.schedule_personalization_config import (  # noqa: E402
    load_personalization_runtime_config,
)


class PersonalizationContractTests(unittest.TestCase):
    def test_enum_values_and_json_serialization_are_stable(self):
        hypothesis = TaskArchetypeHypothesis(
            task_archetype=TaskArchetype.essay_draft,
            subject="Economics",
            confidence=0.6,
            provenance=EvidenceProvenance.llm_candidate,
        )
        payload = hypothesis.model_dump(mode="json")
        self.assertEqual("essay_draft", payload["task_archetype"])
        self.assertEqual("llm_candidate", payload["provenance"])

    def test_contracts_forbid_unknown_and_unsafe_values(self):
        with self.assertRaises(ValidationError):
            SourceReference(source_type="conversation", source_id=1)
        with self.assertRaises(ValidationError):
            WorkEventInput(
                event_type=WorkEventType.started,
                source={"source_type": "task", "source_id": 1},
                idempotency_key="valid-key",
                unknown_authority=True,
            )
        with self.assertRaises(ValidationError):
            TaskArchetypeHypothesis(confidence=1.1)
        with self.assertRaises(ValidationError):
            WorkEventInput(
                event_type="started",
                source={"source_type": "task", "source_id": 1},
                idempotency_key="valid-key",
                confidence="certain",
            )

    def test_consent_dependencies_default_private(self):
        defaults = ConsentSettingsUpdate()
        self.assertFalse(defaults.operational_personalization_enabled)
        self.assertFalse(defaults.work_session_capture_enabled)
        self.assertFalse(defaults.cross_user_learning_enabled)
        self.assertEqual(365, defaults.raw_event_retention_days)
        with self.assertRaises(ValidationError):
            ConsentSettingsUpdate(near_tie_exploration_enabled=True)

    def test_decision_candidates_are_closed_and_referenced(self):
        candidate = DecisionCandidateContract(
            candidate_id="task:1:2026-08-10",
            local_date=date(2026, 8, 10),
            deterministic_rank=1,
            deterministic_score=0.4,
            reason_codes=["balanced_capacity"],
            effort_hours=1.5,
            energy_points=1.5,
        )
        observation = DecisionObservationInput(
            decision_point_id=uuid4(),
            source={"source_type": "task", "source_id": 1},
            occurred_at=datetime.now(timezone.utc),
            local_date=date(2026, 8, 5),
            timezone="Asia/Shanghai",
            context_hash="a" * 64,
            candidates=[candidate],
            displayed_candidate_ids=[candidate.candidate_id],
            selected_candidate_id=candidate.candidate_id,
            policy_version="energy-waterline-v1",
        )
        self.assertIsNone(observation.action_propensity)
        with self.assertRaises(ValidationError):
            observation.model_copy(update={"displayed_candidate_ids": ["not-eligible"]}).model_validate(
                observation.model_copy(update={"displayed_candidate_ids": ["not-eligible"]}).model_dump()
            )

    def test_llm_reflection_requires_evidence_and_confidence(self):
        with self.assertRaises(ValidationError):
            MemoryEntryInput(
                tier=MemoryTier.llm_reflection,
                memory_key="writing_overrun",
                display_text="Recent writing took longer.",
            )
        entry = MemoryEntryInput(
            tier=MemoryTier.llm_reflection,
            memory_key="writing_overrun",
            display_text="Recent writing took longer.",
            evidence_event_ids=[uuid4()],
            confidence=0.7,
        )
        self.assertEqual(MemoryTier.llm_reflection, entry.tier)

    def test_randomized_exposure_can_record_an_unlisted_user_choice(self):
        candidate = DecisionCandidateContract(
            candidate_id="safe-a",
            local_date=date(2026, 8, 5),
            deterministic_rank=1,
            deterministic_score=0.1,
            reason_codes=["safe"],
            effort_hours=1,
            energy_points=1,
        )
        second = DecisionCandidateContract(
            candidate_id="safe-b",
            local_date=date(2026, 8, 6),
            deterministic_rank=2,
            deterministic_score=0.2,
            reason_codes=["safe"],
            effort_hours=1,
            energy_points=1,
        )
        observation = DecisionObservationInput(
            decision_point_id=uuid4(),
            source={"source_type": "task", "source_id": 1},
            occurred_at=datetime.now(timezone.utc),
            local_date=date(2026, 8, 5),
            timezone="Asia/Shanghai",
            context_hash="b" * 64,
            candidates=[candidate, second],
            displayed_candidate_ids=["safe-b", "safe-a"],
            selected_candidate_id="unlisted-date",
            selection_source="user_unlisted",
            randomized_assignment=True,
            action_propensity=0.5,
            policy_version="energy-waterline-v1",
        )
        self.assertTrue(observation.randomized_assignment)
        self.assertEqual(0.5, observation.action_propensity)

    def test_model_artifact_is_json_only_and_bounded(self):
        artifact = ModelArtifactContract(model_type=ModelType.effort, artifact_json={"mean": 2.1})
        self.assertEqual("effort", artifact.model_dump(mode="json")["model_type"])
        with self.assertRaises(ValidationError):
            ModelArtifactContract(
                model_type=ModelType.effort,
                artifact_json={"callable": lambda: None},
            )
        with self.assertRaises(ValidationError):
            ModelArtifactContract(
                model_type=ModelType.effort,
                artifact_json={"mean": float("nan")},
            )
        with self.assertRaises(ValidationError):
            ModelArtifactContract(
                model_type=ModelType.effort,
                artifact_json={"oversized": "x" * 70_000},
            )


class PersonalizationRuntimeConfigTests(unittest.TestCase):
    def test_defaults_are_private_and_deterministic(self):
        config = load_personalization_runtime_config({})
        self.assertFalse(config.effective_capture_enabled)
        self.assertFalse(config.effective_exploration_enabled)
        self.assertEqual(ServingMode.disabled, config.effective_serving_mode)
        self.assertEqual(365, config.raw_event_retention_days)
        self.assertEqual(5, config.effort_observation_threshold)
        self.assertEqual(20, config.ranking_decision_threshold)

    def test_suggestion_and_exploration_require_the_full_global_chain(self):
        partial = load_personalization_runtime_config({
            "SCHEDULING_PERSONALIZATION_SUGGESTION_ENABLED": "true",
            "SCHEDULING_NEAR_TIE_EXPLORATION_ENABLED": "true",
        })
        self.assertEqual(ServingMode.disabled, partial.effective_serving_mode)
        self.assertFalse(partial.effective_exploration_enabled)

        enabled = load_personalization_runtime_config({
            "SCHEDULING_PERSONALIZATION_ENABLED": "true",
            "SCHEDULING_PERSONAL_MODELING_ENABLED": "true",
            "SCHEDULING_PERSONALIZATION_SUGGESTION_ENABLED": "true",
            "SCHEDULING_NEAR_TIE_EXPLORATION_ENABLED": "true",
        })
        self.assertEqual(ServingMode.suggestion, enabled.effective_serving_mode)
        self.assertTrue(enabled.effective_exploration_enabled)

    def test_kill_and_malformed_values_fail_toward_baseline(self):
        config = load_personalization_runtime_config({
            "SCHEDULING_PERSONALIZATION_ENABLED": "true",
            "SCHEDULING_PERSONAL_MODELING_ENABLED": "true",
            "SCHEDULING_PERSONALIZATION_SHADOW_ENABLED": "true",
            "SCHEDULING_PERSONALIZATION_KILL_SWITCH": "true",
            "SCHEDULING_RAW_EVENT_RETENTION_DAYS": "invalid",
            "SCHEDULING_RANKING_DECISION_THRESHOLD": "-5",
        })
        self.assertEqual(ServingMode.killed, config.effective_serving_mode)
        self.assertEqual(365, config.raw_event_retention_days)
        self.assertEqual(20, config.ranking_decision_threshold)

        unknown_boolean = load_personalization_runtime_config({
            "SCHEDULING_PERSONALIZATION_ENABLED": "perhaps",
        })
        self.assertEqual(ServingMode.disabled, unknown_boolean.effective_serving_mode)


if __name__ == "__main__":
    unittest.main()
