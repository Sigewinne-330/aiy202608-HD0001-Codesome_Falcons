"""Strict automatic reflection materialization with abstention by default."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingMemoryEntry, SchedulingWorkEvent
from schemas.schedule_personalization import MemoryEntryInput, MemoryTier
from services.schedule_memory import (
    MemoryError,
    MemoryEvidenceError,
    _evidence_hash,
    _evidence_rows,
    create_memory_entry,
)
from services.schedule_personalization_governance import get_or_create_private_consent


PROHIBITED_CLAIM_TERMS = {
    "ability",
    "adhd",
    "anxiety",
    "autism",
    "bipolar",
    "depression",
    "diagnosis",
    "disability",
    "health condition",
    "intelligence",
    "iq",
    "lazy",
    "mental health",
    "personality",
    "psychological trait",
    "stupid",
    "抑郁",
    "智力",
    "懒惰",
    "心理疾病",
    "人格",
    "注意力缺陷",
}


@dataclass(frozen=True)
class ReflectionMaterializationResult:
    state: str
    reason: str
    memory: Optional[SchedulingMemoryEntry] = None


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _fingerprint(data: MemoryEntryInput, evidence_hash: str) -> str:
    payload = {
        "memory_key": data.memory_key.strip().lower(),
        "value": data.value_json,
        "evidence_hash": evidence_hash,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def materialize_reflection_candidate(
    db: Session,
    user_id: int,
    candidate_output: Any,
    *,
    generated_by_model: str,
    prompt_version: str,
    minimum_evidence: int = 2,
    minimum_confidence: float = 0.55,
) -> ReflectionMaterializationResult:
    try:
        data = MemoryEntryInput.model_validate(candidate_output)
    except (ValidationError, TypeError, ValueError):
        return ReflectionMaterializationResult("abstained", "invalid_schema")
    if data.tier != MemoryTier.llm_reflection:
        return ReflectionMaterializationResult("abstained", "invalid_tier")
    if not generated_by_model or not prompt_version:
        return ReflectionMaterializationResult("abstained", "missing_generation_lineage")
    if data.confidence is None or data.confidence < minimum_confidence:
        return ReflectionMaterializationResult("abstained", "weak_confidence")
    combined_text = f"{data.memory_key} {data.display_text} {_flatten_text(data.value_json)}".lower()
    if any(term in combined_text for term in PROHIBITED_CLAIM_TERMS):
        return ReflectionMaterializationResult("abstained", "prohibited_claim")

    consent = get_or_create_private_consent(db, user_id)
    if not consent.operational_personalization_enabled or not consent.llm_memory_enabled:
        return ReflectionMaterializationResult("abstained", "consent_disabled")
    event_ids = [str(value) for value in data.evidence_event_ids]
    if len(set(event_ids)) < minimum_evidence:
        return ReflectionMaterializationResult("abstained", "insufficient_evidence")
    try:
        _evidence_rows(db, user_id, event_ids, consent.eligibility_watermark)
    except MemoryEvidenceError:
        return ReflectionMaterializationResult("abstained", "invalid_evidence")
    work_quality = db.query(SchedulingWorkEvent).filter(
        SchedulingWorkEvent.user_id == user_id,
        SchedulingWorkEvent.event_id.in_(event_ids),
        SchedulingWorkEvent.confidence.in_(["high", "medium"]),
        SchedulingWorkEvent.invalidated_at.is_(None),
    ).count()
    non_work_count = len(event_ids) - db.query(SchedulingWorkEvent).filter(
        SchedulingWorkEvent.user_id == user_id,
        SchedulingWorkEvent.event_id.in_(event_ids),
    ).count()
    if work_quality + non_work_count < minimum_evidence:
        return ReflectionMaterializationResult("abstained", "weak_evidence_quality")

    evidence_hash = _evidence_hash(event_ids)
    fingerprint = _fingerprint(data, evidence_hash)
    if db.query(SchedulingMemoryEntry).filter(
        SchedulingMemoryEntry.user_id == user_id,
        SchedulingMemoryEntry.suppression_fingerprint == fingerprint,
        SchedulingMemoryEntry.status.in_(["deleted", "dismissed"]),
    ).first():
        return ReflectionMaterializationResult("suppressed", "user_suppression")

    explicit = db.query(SchedulingMemoryEntry).filter(
        SchedulingMemoryEntry.user_id == user_id,
        SchedulingMemoryEntry.memory_key == data.memory_key,
        SchedulingMemoryEntry.tier == MemoryTier.explicit_declaration.value,
        SchedulingMemoryEntry.status == "current",
        SchedulingMemoryEntry.invalidated_at.is_(None),
        SchedulingMemoryEntry.deleted_at.is_(None),
    ).first()
    if explicit is not None:
        return ReflectionMaterializationResult("abstained", "explicit_authority_exists")

    same_evidence = db.query(SchedulingMemoryEntry).filter(
        SchedulingMemoryEntry.user_id == user_id,
        SchedulingMemoryEntry.memory_key == data.memory_key,
        SchedulingMemoryEntry.tier == MemoryTier.llm_reflection.value,
        SchedulingMemoryEntry.evidence_hash == evidence_hash,
        SchedulingMemoryEntry.status == "current",
        SchedulingMemoryEntry.invalidated_at.is_(None),
    ).first()
    if same_evidence is not None:
        if same_evidence.suppression_fingerprint == fingerprint:
            return ReflectionMaterializationResult("duplicate", "unchanged_evidence", same_evidence)
        return ReflectionMaterializationResult("abstained", "contradictory_same_evidence")

    try:
        memory = create_memory_entry(
            db,
            user_id,
            data,
            source="llm",
            generated_by_model=generated_by_model,
            prompt_version=prompt_version,
        )
    except (MemoryError, MemoryEvidenceError):
        return ReflectionMaterializationResult("abstained", "validation_failed")
    memory.suppression_fingerprint = fingerprint
    prior_rows = db.query(SchedulingMemoryEntry).filter(
        SchedulingMemoryEntry.user_id == user_id,
        SchedulingMemoryEntry.memory_key == data.memory_key,
        SchedulingMemoryEntry.tier == MemoryTier.llm_reflection.value,
        SchedulingMemoryEntry.id != memory.id,
        SchedulingMemoryEntry.status == "current",
        SchedulingMemoryEntry.invalidated_at.is_(None),
    ).all()
    for prior in prior_rows:
        prior.status = "superseded" if prior.value_json == memory.value_json else "contradicted"
        prior.contradiction_state = "newer_evidence" if prior.value_json != memory.value_json else "none"
        prior.superseded_by_memory_id = memory.memory_id
        memory.supersedes_memory_id = prior.memory_id
    db.flush()
    return ReflectionMaterializationResult("created", "eligible_evidence", memory)
