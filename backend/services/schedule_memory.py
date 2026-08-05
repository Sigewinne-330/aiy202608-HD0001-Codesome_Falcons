"""Authority-separated scheduling memory and bounded retrieval."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from models.schedule_personalization import (
    SchedulingDecisionEvent,
    SchedulingMemoryEntry,
    SchedulingWorkEvent,
)
from schemas.schedule_personalization import (
    MEMORY_SCHEMA_VERSION,
    MemoryEntryInput,
    MemoryEntryUpdate,
    MemoryPurpose,
    MemoryTier,
)
from services.schedule_personalization_governance import get_or_create_private_consent
from services.schedule_personalization_governance import enqueue_governance_job, invalidate_memory_entry
from services.schedule_source_access import owned_schedule_source


class MemoryError(ValueError):
    pass


class MemoryEvidenceError(MemoryError):
    pass


class MemoryNotFound(MemoryError):
    pass


class MemoryEditConflict(MemoryError):
    pass


PROHIBITED_AUTHORITY_KEYS = {
    "chat_history",
    "developer_prompt",
    "role_card",
    "role_card_id",
    "system_prompt",
    "tool_instruction",
}

PURPOSE_TIERS = {
    MemoryPurpose.extraction: {MemoryTier.explicit_declaration.value},
    MemoryPurpose.clarification: {
        MemoryTier.explicit_declaration.value,
        MemoryTier.temporary_context.value,
    },
    MemoryPurpose.reflection: {MemoryTier.explicit_declaration.value},
    MemoryPurpose.explanation: {
        MemoryTier.explicit_declaration.value,
        MemoryTier.llm_reflection.value,
        MemoryTier.temporary_context.value,
    },
    MemoryPurpose.ranking: {MemoryTier.explicit_declaration.value},
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _contains_prohibited_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).strip().lower() in PROHIBITED_AUTHORITY_KEYS
            or _contains_prohibited_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_prohibited_key(item) for item in value)
    return False


def _evidence_rows(db: Session, user_id: int, event_ids: list[str], watermark: int) -> list[object]:
    if not event_ids:
        return []
    work = db.query(SchedulingWorkEvent).filter(
        SchedulingWorkEvent.user_id == user_id,
        SchedulingWorkEvent.event_id.in_(event_ids),
        SchedulingWorkEvent.eligible_personal.is_(True),
        SchedulingWorkEvent.eligibility_watermark == watermark,
        SchedulingWorkEvent.invalidated_at.is_(None),
    ).all()
    found = {row.event_id for row in work}
    remaining = set(event_ids) - found
    decisions = []
    if remaining:
        decisions = db.query(SchedulingDecisionEvent).filter(
            SchedulingDecisionEvent.user_id == user_id,
            SchedulingDecisionEvent.decision_point_id.in_(remaining),
            SchedulingDecisionEvent.eligible_personal.is_(True),
            SchedulingDecisionEvent.eligibility_watermark == watermark,
            SchedulingDecisionEvent.invalidated_at.is_(None),
        ).all()
        found.update(row.decision_point_id for row in decisions)
    if found != set(event_ids):
        raise MemoryEvidenceError("memory evidence is missing, foreign, or analytically ineligible")
    return [*work, *decisions]


def _evidence_hash(event_ids: list[str]) -> Optional[str]:
    if not event_ids:
        return None
    encoded = json.dumps(sorted(event_ids), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_memory_entry(
    db: Session,
    user_id: int,
    data: MemoryEntryInput,
    *,
    source: str,
    generated_by_model: Optional[str] = None,
    prompt_version: Optional[str] = None,
) -> SchedulingMemoryEntry:
    if source not in {"user", "llm", "session"}:
        raise MemoryError("unsupported memory source")
    if _contains_prohibited_key(data.value_json) or data.memory_key.lower() in PROHIBITED_AUTHORITY_KEYS:
        raise MemoryError("prompt, role-card, chat, and tool instructions cannot become memory authority")
    if data.tier == MemoryTier.explicit_declaration and source != "user":
        raise MemoryError("only the user can author an explicit declaration")
    if data.tier == MemoryTier.llm_reflection and source != "llm":
        raise MemoryError("LLM reflection source must be llm")
    if data.tier == MemoryTier.temporary_context and source != "session":
        raise MemoryError("temporary context source must be session")

    consent = get_or_create_private_consent(db, user_id)
    if data.tier == MemoryTier.llm_reflection:
        if not consent.operational_personalization_enabled or not consent.llm_memory_enabled:
            raise MemoryError("LLM memory is not consent-enabled")
    event_ids = [str(value) for value in data.evidence_event_ids]
    _evidence_rows(db, user_id, event_ids, consent.eligibility_watermark)
    now = _now()
    valid_from = data.valid_from or date.today()
    valid_until = data.valid_until
    expires_at = None
    if data.tier == MemoryTier.llm_reflection:
        valid_until = valid_until or (date.today() + timedelta(days=30))
        expires_at = datetime.combine(valid_until + timedelta(days=1), time.min)
    elif data.tier == MemoryTier.temporary_context:
        valid_until = valid_until or date.today()
        expires_at = now + timedelta(days=1)

    row = SchedulingMemoryEntry(
        memory_id=str(uuid4()),
        user_id=user_id,
        tier=data.tier.value,
        memory_key=data.memory_key,
        value_json=data.value_json,
        display_text=data.display_text,
        source=source,
        evidence_event_ids=event_ids,
        evidence_hash=_evidence_hash(event_ids),
        evidence_count=len(event_ids),
        confidence=data.confidence,
        maturity=min(1.0, len(event_ids) / 5.0) if data.tier == MemoryTier.llm_reflection else None,
        valid_from=valid_from,
        valid_until=valid_until,
        expires_at=expires_at,
        generated_by_model=generated_by_model,
        prompt_version=prompt_version,
        schema_version=data.schema_version or MEMORY_SCHEMA_VERSION,
        status="current",
        consent_version=consent.version,
        eligibility_watermark=consent.eligibility_watermark,
    )
    db.add(row)
    db.flush()

    current = db.query(SchedulingMemoryEntry).filter(
        SchedulingMemoryEntry.user_id == user_id,
        SchedulingMemoryEntry.memory_key == data.memory_key,
        SchedulingMemoryEntry.id != row.id,
        SchedulingMemoryEntry.status == "current",
        SchedulingMemoryEntry.deleted_at.is_(None),
        SchedulingMemoryEntry.invalidated_at.is_(None),
    ).all()
    if data.tier == MemoryTier.explicit_declaration:
        for prior in current:
            if prior.tier == MemoryTier.llm_reflection.value:
                prior.status = "contradicted"
                prior.contradiction_state = "contradicted_by_explicit"
                prior.superseded_by_memory_id = row.memory_id
            elif prior.tier == MemoryTier.explicit_declaration.value:
                # A bounded dated exception coexists with an undated/stable rule.
                dated_exception = data.valid_until is not None and prior.valid_until is None
                if not dated_exception:
                    prior.status = "superseded"
                    prior.superseded_by_memory_id = row.memory_id
                    row.supersedes_memory_id = prior.memory_id
    db.flush()
    return row


def _context_matches(value: dict, subject: Optional[str], task_archetype: Optional[str]) -> bool:
    memory_subject = value.get("subject")
    memory_archetype = value.get("task_archetype")
    if subject and memory_subject and str(memory_subject).lower() != subject.lower():
        return False
    if task_archetype and memory_archetype and memory_archetype != task_archetype:
        return False
    return True


def retrieve_memory_projection(
    db: Session,
    user_id: int,
    *,
    purpose: MemoryPurpose,
    reference_date: Optional[date] = None,
    subject: Optional[str] = None,
    task_archetype: Optional[str] = None,
    limit: int = 12,
    maximum_bytes: int = 8_192,
) -> dict:
    if limit < 1 or limit > 20 or maximum_bytes < 256 or maximum_bytes > 32_768:
        raise MemoryError("memory retrieval bounds are invalid")
    consent = get_or_create_private_consent(db, user_id)
    if not consent.operational_personalization_enabled:
        return {"schema_version": MEMORY_SCHEMA_VERSION, "purpose": purpose.value, "items": [], "truncated": False}
    today = reference_date or date.today()
    now = _now()
    rows = db.query(SchedulingMemoryEntry).filter(
        SchedulingMemoryEntry.user_id == user_id,
        SchedulingMemoryEntry.tier.in_(PURPOSE_TIERS[purpose]),
        SchedulingMemoryEntry.status == "current",
        SchedulingMemoryEntry.eligibility_watermark == consent.eligibility_watermark,
        SchedulingMemoryEntry.invalidated_at.is_(None),
        SchedulingMemoryEntry.deleted_at.is_(None),
    ).order_by(SchedulingMemoryEntry.updated_at.desc(), SchedulingMemoryEntry.id.desc()).all()

    eligible = []
    for row in rows:
        if row.valid_from and row.valid_from > today:
            continue
        if row.valid_until and row.valid_until < today:
            continue
        if row.expires_at and row.expires_at <= now:
            continue
        if row.tier == MemoryTier.llm_reflection.value and not consent.llm_memory_enabled:
            continue
        if not _context_matches(row.value_json or {}, subject, task_archetype):
            continue
        eligible.append(row)

    # Explicit, dated declarations outrank stable declarations and all reflections.
    eligible.sort(key=lambda row: (
        0 if row.tier == MemoryTier.explicit_declaration.value else 1 if row.tier == MemoryTier.temporary_context.value else 2,
        0 if row.valid_until is not None else 1,
        -row.id,
    ))
    items = []
    truncated = len(eligible) > limit
    for row in eligible:
        projection = {
            "memory_id": row.memory_id,
            "tier": row.tier,
            "authority": "user_explicit" if row.tier == MemoryTier.explicit_declaration.value else "hypothesis",
            "memory_key": row.memory_key,
            "value": row.value_json,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "valid_from": row.valid_from.isoformat() if row.valid_from else None,
            "valid_until": row.valid_until.isoformat() if row.valid_until else None,
            "evidence_count": int(row.evidence_count or 0),
        }
        candidate = [*items, projection]
        encoded_size = len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if len(items) >= limit or encoded_size > maximum_bytes:
            truncated = True
            break
        items.append(projection)
        row.last_retrieved_at = now
        row.last_used_purpose = purpose.value
    db.flush()
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "purpose": purpose.value,
        "items": items,
        "truncated": truncated,
    }


def get_owned_memory(db: Session, user_id: int, memory_id: str) -> SchedulingMemoryEntry:
    row = db.query(SchedulingMemoryEntry).filter_by(
        user_id=user_id,
        memory_id=memory_id,
    ).one_or_none()
    if row is None:
        raise MemoryNotFound("memory does not exist or is not accessible")
    return row


def _evidence_projection(db: Session, user_id: int, event_ids: list[str]) -> list[dict]:
    result = []
    for event_id in event_ids:
        work = db.query(SchedulingWorkEvent).filter_by(user_id=user_id, event_id=event_id).one_or_none()
        if work is not None:
            result.append({
                "event_id": event_id,
                "kind": "work_event",
                "event_type": work.event_type,
                "observed_at": work.effective_at,
                "confidence": work.confidence,
                "eligible": bool(work.eligible_personal and work.invalidated_at is None),
                "source_available": owned_schedule_source(
                    db, user_id, work.source_type, work.source_id
                ) is not None,
            })
            continue
        decision = db.query(SchedulingDecisionEvent).filter_by(
            user_id=user_id,
            decision_point_id=event_id,
        ).one_or_none()
        if decision is not None:
            result.append({
                "event_id": event_id,
                "kind": "decision_event",
                "event_type": "decision",
                "observed_at": decision.occurred_at,
                "confidence": None,
                "eligible": bool(decision.eligible_personal and decision.invalidated_at is None),
                "source_available": owned_schedule_source(
                    db, user_id, decision.source_type, decision.source_id
                ) is not None,
            })
            continue
        result.append({
            "event_id": event_id,
            "kind": "unavailable",
            "event_type": None,
            "observed_at": None,
            "confidence": None,
            "eligible": False,
            "source_available": False,
        })
    return result


def memory_entry_payload(
    db: Session,
    row: SchedulingMemoryEntry,
    *,
    include_evidence: bool = False,
) -> dict:
    payload = {
        "memory_id": row.memory_id,
        "tier": row.tier,
        "authority": "user_explicit" if row.tier == MemoryTier.explicit_declaration.value else "hypothesis",
        "memory_key": row.memory_key,
        "value_json": row.value_json,
        "display_text": row.display_text,
        "source": row.source,
        "evidence_count": int(row.evidence_count or 0),
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "maturity": float(row.maturity) if row.maturity is not None else None,
        "valid_from": row.valid_from,
        "valid_until": row.valid_until,
        "expires_at": row.expires_at,
        "status": row.status,
        "contradiction_state": row.contradiction_state,
        "supersedes_memory_id": row.supersedes_memory_id,
        "superseded_by_memory_id": row.superseded_by_memory_id,
        "schema_version": row.schema_version,
        "last_retrieved_at": row.last_retrieved_at,
        "last_used_purpose": row.last_used_purpose,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "editable": row.tier == MemoryTier.explicit_declaration.value and row.status == "current",
        "deletable": row.deleted_at is None,
    }
    if include_evidence:
        payload["evidence"] = _evidence_projection(db, row.user_id, list(row.evidence_event_ids or []))
    return payload


def list_memory_entries(
    db: Session,
    user_id: int,
    *,
    tier: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = "current",
    search: Optional[str] = None,
    before_memory_id: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[SchedulingMemoryEntry], Optional[str]]:
    if limit < 1 or limit > 100:
        raise MemoryError("memory page limit is invalid")
    query = db.query(SchedulingMemoryEntry).filter(SchedulingMemoryEntry.user_id == user_id)
    if tier:
        query = query.filter(SchedulingMemoryEntry.tier == tier)
    if source:
        query = query.filter(SchedulingMemoryEntry.source == source)
    if status:
        query = query.filter(SchedulingMemoryEntry.status == status)
    if search:
        query = query.filter(
            SchedulingMemoryEntry.display_text.contains(search[:100])
            | SchedulingMemoryEntry.memory_key.contains(search[:100])
        )
    if before_memory_id:
        cursor = get_owned_memory(db, user_id, before_memory_id)
        query = query.filter(SchedulingMemoryEntry.id < cursor.id)
    rows = query.order_by(SchedulingMemoryEntry.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = page[-1].memory_id if has_more and page else None
    return page, next_cursor


def edit_explicit_memory(
    db: Session,
    user_id: int,
    memory_id: str,
    data: MemoryEntryUpdate,
) -> SchedulingMemoryEntry:
    prior = get_owned_memory(db, user_id, memory_id)
    if prior.tier != MemoryTier.explicit_declaration.value or prior.status != "current":
        raise MemoryEditConflict("only a current explicit declaration can be edited")
    return create_memory_entry(
        db,
        user_id,
        MemoryEntryInput(
            tier=MemoryTier.explicit_declaration,
            memory_key=prior.memory_key,
            value_json=data.value_json if data.value_json is not None else prior.value_json,
            display_text=data.display_text if data.display_text is not None else prior.display_text,
            evidence_event_ids=[],
            valid_from=data.valid_from if data.valid_from is not None else prior.valid_from,
            valid_until=data.valid_until if data.valid_until is not None else prior.valid_until,
            schema_version=prior.schema_version,
        ),
        source="user",
    )


def delete_owned_memory(db: Session, user_id: int, memory_id: str) -> SchedulingMemoryEntry:
    row = get_owned_memory(db, user_id, memory_id)
    if row.deleted_at is not None:
        return row
    suppression = row.suppression_fingerprint or hashlib.sha256(
        f"deleted-memory:{row.memory_id}".encode("utf-8")
    ).hexdigest()
    deleted = invalidate_memory_entry(
        db,
        user_id,
        memory_id,
        suppression_fingerprint=suppression,
    )
    if deleted is None:
        raise MemoryNotFound("memory does not exist or is not accessible")
    enqueue_governance_job(
        db,
        idempotency_key=f"memory-delete:{user_id}:{row.memory_id}",
        job_type="propagate_deletion",
        user_id=user_id,
        payload={"target": "memory", "memory_id": row.memory_id},
    )
    return deleted
