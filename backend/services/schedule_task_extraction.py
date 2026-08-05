"""Consent-gated, bounded task extraction with deterministic authority.

LLM output is always a candidate hypothesis.  It can enrich scope fields but
cannot create a confirmed preference, a learned coefficient, or a memory row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from pydantic import ConfigDict, BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from schemas.schedule_personalization import (
    EvidenceProvenance,
    MemoryPurpose,
    TASK_TAXONOMY_VERSION,
    TaskArchetype,
    TaskArchetypeHypothesis,
)
from services.schedule_llm_memory import (
    ProviderCallable,
    build_bounded_llm_projection,
    run_bounded_llm_operation,
)
from services.schedule_personalization_config import PersonalizationRuntimeConfig
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_taxonomy import (
    ARCHETYPE_DEFINITIONS,
    IB_SUBJECT_DEFINITIONS,
    normalize_ib_subject,
    normalize_task_archetype,
)


TASK_EXTRACTION_SCHEMA_VERSION = "scheduling-task-extraction.v1"
ALLOWED_DELIVERABLE_UNITS = frozenset({
    "actions", "cards", "chapters", "deliverables", "forms", "hours", "items",
    "milestones", "minutes", "pages", "papers", "problems", "questions", "runs",
    "samples", "sections", "slides", "sources", "stages", "topics", "words",
})
ALLOWED_STAGES = frozenset({
    "analysis", "data_collection", "final", "first_draft", "planning", "practice",
    "rehearsal", "research", "revision", "submission", "unknown",
})


class _ProviderExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_archetype: TaskArchetype = TaskArchetype.unknown
    subject: Optional[str] = Field(default=None, max_length=100)
    deliverable_unit: Optional[str] = Field(default=None, max_length=32)
    deliverable_quantity: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    stage: Optional[str] = Field(default=None, max_length=50)
    novelty: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")
    complexity: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")
    ambiguity: str = Field(default="high", pattern="^(low|medium|high)$")
    confidence: float = Field(default=0, ge=0, le=1)

    @field_validator("deliverable_unit")
    @classmethod
    def validate_unit(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.casefold().replace(" ", "_")
        if normalized not in ALLOWED_DELIVERABLE_UNITS:
            raise ValueError("unsupported deliverable unit")
        return normalized

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.casefold().replace(" ", "_")
        if normalized not in ALLOWED_STAGES:
            raise ValueError("unsupported task stage")
        return normalized

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.deliverable_quantity is not None and self.deliverable_unit is None:
            raise ValueError("deliverable quantity requires a unit")
        if self.task_archetype == TaskArchetype.unknown and self.confidence > 0.2:
            raise ValueError("unknown archetype cannot claim high extraction confidence")
        return self


@dataclass(frozen=True)
class TaskExtractionResult:
    hypothesis: TaskArchetypeHypothesis
    subject_status: str
    matched_subjects: tuple[str, ...]
    field_provenance: dict[str, str]
    conflict_codes: tuple[str, ...]
    used_provider: bool
    fallback_reason: Optional[str]
    provider_name: Optional[str]
    model_name: Optional[str]
    confirmed_user_fact: bool
    coefficient_authority: bool
    extraction_schema_version: str
    audit: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        return {
            "hypothesis": self.hypothesis.model_dump(mode="json"),
            "subject_status": self.subject_status,
            "matched_subjects": list(self.matched_subjects),
            "field_provenance": dict(self.field_provenance),
            "conflict_codes": list(self.conflict_codes),
            "used_provider": self.used_provider,
            "fallback_reason": self.fallback_reason,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "confirmed_user_fact": self.confirmed_user_fact,
            "coefficient_authority": self.coefficient_authority,
            "extraction_schema_version": self.extraction_schema_version,
            "audit": dict(self.audit),
        }


def _deterministic_base(current_task: dict[str, Any]):
    structured_kind = current_task.get("task_archetype") or current_task.get("schedule_kind")
    structured_version = current_task.get("taxonomy_version") or TASK_TAXONOMY_VERSION
    archetype = normalize_task_archetype(
        title=current_task.get("title"),
        description=current_task.get("description"),
        structured_kind=structured_kind,
        structured_taxonomy_version=structured_version,
    )
    subject = normalize_ib_subject(current_task.get("subject"))
    if archetype.provenance == "structured":
        provenance = EvidenceProvenance.direct_user
    elif archetype.provenance == "migrated_structured":
        provenance = EvidenceProvenance.imported
    elif archetype.provenance == "deterministic_alias":
        provenance = EvidenceProvenance.derived
    else:
        provenance = EvidenceProvenance.product_default
    hypothesis = TaskArchetypeHypothesis(
        task_archetype=archetype.task_archetype,
        subject=subject.subject,
        ambiguity=archetype.ambiguity,
        confidence=archetype.confidence,
        provenance=provenance,
        schema_version=TASK_EXTRACTION_SCHEMA_VERSION,
        taxonomy_version=TASK_TAXONOMY_VERSION,
    )
    field_provenance = {
        "task_archetype": provenance.value,
        "subject": "direct_user" if subject.status != "unknown" else "product_default",
    }
    return hypothesis, archetype, subject, field_provenance


def _llm_allowed(db: Session, user_id: int, config: PersonalizationRuntimeConfig) -> bool:
    consent = get_or_create_private_consent(db, user_id)
    return bool(
        consent.operational_personalization_enabled
        and consent.llm_memory_enabled
        and config.effective_reflection_enabled
    )


def _fallback_result(
    *,
    hypothesis: TaskArchetypeHypothesis,
    subject_status: str,
    matched_subjects: tuple[str, ...],
    field_provenance: dict[str, str],
    fallback_reason: str,
    provider_name: Optional[str],
    model_name: Optional[str],
    audit: Optional[dict[str, Any]] = None,
) -> TaskExtractionResult:
    return TaskExtractionResult(
        hypothesis=hypothesis,
        subject_status=subject_status,
        matched_subjects=matched_subjects,
        field_provenance=field_provenance,
        conflict_codes=(),
        used_provider=False,
        fallback_reason=fallback_reason,
        provider_name=provider_name,
        model_name=model_name,
        confirmed_user_fact=False,
        coefficient_authority=False,
        extraction_schema_version=TASK_EXTRACTION_SCHEMA_VERSION,
        audit=audit or {"provider_invoked": False, "memory_written": False},
    )


async def extract_task_hypothesis(
    db: Session,
    user_id: int,
    *,
    current_task: dict[str, Any],
    runtime_config: PersonalizationRuntimeConfig,
    provider: Optional[ProviderCallable],
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    timeout_seconds: float = 8.0,
) -> TaskExtractionResult:
    base, deterministic, subject, field_provenance = _deterministic_base(current_task)
    if not _llm_allowed(db, user_id, runtime_config):
        return _fallback_result(
            hypothesis=base,
            subject_status=subject.status,
            matched_subjects=subject.matched_subjects,
            field_provenance=field_provenance,
            fallback_reason="llm_extraction_not_consented_or_disabled",
            provider_name=provider_name,
            model_name=model_name,
        )

    deterministic_context = {
        "taxonomy_version": TASK_TAXONOMY_VERSION,
        "allowed_task_archetypes": [item.code for item in ARCHETYPE_DEFINITIONS],
        "allowed_subjects": [item.code for item in IB_SUBJECT_DEFINITIONS],
        "allowed_units": sorted(ALLOWED_DELIVERABLE_UNITS),
        "allowed_stages": sorted(ALLOWED_STAGES),
        "unresolved_fields": [
            field for field, value in (
                ("task_archetype", base.task_archetype.value == "unknown"),
                ("subject", subject.status == "unknown"),
                ("deliverable_quantity", True),
            ) if value
        ],
    }
    projection = build_bounded_llm_projection(
        db,
        user_id,
        purpose=MemoryPurpose.extraction,
        current_task=current_task,
        deterministic_context=deterministic_context,
        subject=subject.subject,
        task_archetype=base.task_archetype.value,
        maximum_memories=4,
        maximum_bytes=8_192,
    )
    llm_result = await run_bounded_llm_operation(
        projection,
        purpose=MemoryPurpose.extraction,
        deterministic_context=deterministic_context,
        provider=provider,
        timeout_seconds=timeout_seconds,
        max_output_tokens=240,
    )
    audit = {
        **llm_result.audit,
        "provider_invoked": provider is not None,
        "provider_name": provider_name,
        "model_name": model_name,
        "memory_written": False,
        "confirmed_user_fact": False,
        "coefficient_authority": False,
    }
    if not llm_result.used_provider:
        return _fallback_result(
            hypothesis=base,
            subject_status=subject.status,
            matched_subjects=subject.matched_subjects,
            field_provenance=field_provenance,
            fallback_reason=llm_result.fallback_reason or "provider_fallback",
            provider_name=provider_name,
            model_name=model_name,
            audit=audit,
        )
    try:
        candidate = _ProviderExtraction.model_validate(llm_result.output)
    except ValidationError:
        return _fallback_result(
            hypothesis=base,
            subject_status=subject.status,
            matched_subjects=subject.matched_subjects,
            field_provenance=field_provenance,
            fallback_reason="invalid_extraction_contract",
            provider_name=provider_name,
            model_name=model_name,
            audit={**audit, "contract_valid": False},
        )

    conflicts: list[str] = []
    final_archetype = candidate.task_archetype
    final_confidence = candidate.confidence
    final_ambiguity = candidate.ambiguity
    archetype_authority = "llm_candidate"
    deterministic_code = base.task_archetype
    if deterministic.provenance in {"structured", "migrated_structured"} and deterministic_code != TaskArchetype.unknown:
        final_archetype = deterministic_code
        final_confidence = base.confidence
        final_ambiguity = base.ambiguity
        archetype_authority = field_provenance["task_archetype"]
        if candidate.task_archetype not in {TaskArchetype.unknown, deterministic_code}:
            conflicts.append("llm_conflicts_with_structured_archetype")
    elif deterministic_code != TaskArchetype.unknown:
        if candidate.task_archetype in {TaskArchetype.unknown, deterministic_code}:
            final_archetype = deterministic_code
            final_confidence = max(base.confidence, min(candidate.confidence, 0.9))
            archetype_authority = "deterministic_alias+llm_candidate"
        else:
            final_archetype = TaskArchetype.mixed
            final_confidence = min(base.confidence, candidate.confidence, 0.5)
            final_ambiguity = "high"
            archetype_authority = "conflicting_candidates"
            conflicts.append("llm_conflicts_with_deterministic_alias")

    candidate_subject = normalize_ib_subject(candidate.subject)
    final_subject = subject.subject
    subject_status = subject.status
    matched_subjects = subject.matched_subjects
    subject_authority = field_provenance["subject"]
    if subject.status == "unknown" and candidate_subject.status == "recognized":
        final_subject = candidate_subject.subject
        subject_status = candidate_subject.status
        matched_subjects = candidate_subject.matched_subjects
        subject_authority = "llm_candidate"
    elif subject.status != "unknown" and candidate_subject.status == "recognized" and candidate_subject.subject != subject.subject:
        conflicts.append("llm_conflicts_with_structured_subject")
    elif subject.status == "unknown" and candidate_subject.status == "mixed":
        subject_status = "mixed"
        matched_subjects = candidate_subject.matched_subjects
        subject_authority = "llm_candidate"

    result_provenance = EvidenceProvenance.llm_candidate
    hypothesis = TaskArchetypeHypothesis(
        task_archetype=final_archetype,
        subject=final_subject,
        deliverable_unit=candidate.deliverable_unit,
        deliverable_quantity=candidate.deliverable_quantity,
        stage=candidate.stage,
        novelty=candidate.novelty,
        complexity=candidate.complexity,
        ambiguity=final_ambiguity,
        confidence=final_confidence,
        provenance=result_provenance,
        schema_version=TASK_EXTRACTION_SCHEMA_VERSION,
        taxonomy_version=TASK_TAXONOMY_VERSION,
    )
    merged_provenance = {
        "task_archetype": archetype_authority,
        "subject": subject_authority,
    }
    for field in ("deliverable_unit", "deliverable_quantity", "stage", "novelty", "complexity", "ambiguity"):
        if getattr(candidate, field) is not None:
            merged_provenance[field] = "llm_candidate"
    return TaskExtractionResult(
        hypothesis=hypothesis,
        subject_status=subject_status,
        matched_subjects=matched_subjects,
        field_provenance=merged_provenance,
        conflict_codes=tuple(conflicts),
        used_provider=True,
        fallback_reason=None,
        provider_name=provider_name,
        model_name=model_name,
        confirmed_user_fact=False,
        coefficient_authority=False,
        extraction_schema_version=TASK_EXTRACTION_SCHEMA_VERSION,
        audit={**audit, "contract_valid": True, "conflict_count": len(conflicts)},
    )

