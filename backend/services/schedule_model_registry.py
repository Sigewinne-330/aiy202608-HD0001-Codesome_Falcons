"""Transactional, data-only registry for adaptive scheduling models.

The registry is deliberately narrower than a generic ML registry.  It stores
only bounded JSON parameters and serves an exact, consent-compatible version.
It never imports, evaluates, deserializes, or otherwise executes artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
import math
from typing import Any, Callable, Mapping, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from models.schedule_personalization import SchedulingModelRegistry
from schemas.schedule_personalization import (
    MAX_MODEL_ARTIFACT_BYTES,
    ModelLifecycle,
    ModelType,
)
from services.schedule_personalization_governance import (
    get_or_create_private_consent,
    utc_now_naive,
)


REGISTRY_SCHEMA_VERSION = "scheduling-model-registry.v1"
ALLOWED_SCOPES = frozenset({"personal", "ib_prior", "global_prior"})
_FORBIDDEN_ARTIFACT_KEYS = frozenset({
    "bytecode",
    "callable",
    "class_path",
    "code",
    "command",
    "eval",
    "exec",
    "executable",
    "import",
    "module",
    "pickle",
    "pickled",
    "script",
    "source_code",
})
_MAX_ARTIFACT_DEPTH = 12
_MAX_ARTIFACT_ITEMS = 2_000


class RegistryError(ValueError):
    """A fail-closed registry contract or lifecycle violation."""


@dataclass(frozen=True)
class RegistryCompatibility:
    algorithm_version: str
    feature_schema_version: str
    label_version: Optional[str] = None
    calibration_version: Optional[str] = None


@dataclass(frozen=True)
class RegistryResolution:
    model: Optional[SchedulingModelRegistry]
    fallback_reason: Optional[str]


def _validate_version(value: Optional[str], field: str, *, required: bool = False) -> Optional[str]:
    if value is None:
        if required:
            raise RegistryError(f"{field} is required")
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise RegistryError(f"{field} must be a non-empty string of at most 64 characters")
    return value.strip()


def _walk_data_only(value: Any, *, depth: int = 0, counter: list[int]) -> None:
    if depth > _MAX_ARTIFACT_DEPTH:
        raise RegistryError("model artifact nesting is too deep")
    counter[0] += 1
    if counter[0] > _MAX_ARTIFACT_ITEMS:
        raise RegistryError("model artifact contains too many values")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RegistryError("model artifact numbers must be finite")
        return
    if isinstance(value, list):
        for item in value:
            _walk_data_only(item, depth=depth + 1, counter=counter)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise RegistryError("model artifact keys must be bounded strings")
            if key.strip().lower() in _FORBIDDEN_ARTIFACT_KEYS:
                raise RegistryError(f"executable artifact field is forbidden: {key}")
            _walk_data_only(item, depth=depth + 1, counter=counter)
        return
    raise RegistryError(f"model artifact contains non-JSON value: {type(value).__name__}")


def validate_data_artifact(value: Mapping[str, Any], *, maximum: int = MAX_MODEL_ARTIFACT_BYTES) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise RegistryError("model artifact must be a non-empty JSON object")
    _walk_data_only(value, counter=[0])
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegistryError("model artifact must be strict JSON data") from exc
    if len(encoded) > maximum:
        raise RegistryError(f"model artifact exceeds {maximum} bytes")
    # Round-trip strips Python container subclasses and gives the ORM a plain,
    # immutable-by-convention snapshot detached from the caller's object.
    return json.loads(encoded.decode("utf-8"))


def _validate_metrics(value: Optional[Mapping[str, Any]], field: str) -> dict[str, Any]:
    if value is None:
        return {}
    try:
        result = validate_data_artifact(dict(value), maximum=32_768) if value else {}
    except RegistryError as exc:
        raise RegistryError(f"invalid {field}: {exc}") from exc
    return result


def _row_signature(row: SchedulingModelRegistry) -> dict[str, Any]:
    return {
        "user_id": row.user_id,
        "model_type": row.model_type,
        "scope": row.scope,
        "algorithm_version": row.algorithm_version,
        "feature_schema_version": row.feature_schema_version,
        "label_version": row.label_version,
        "calibration_version": row.calibration_version,
        "source_eligibility_watermark": row.source_eligibility_watermark,
        "artifact_json": row.artifact_json,
        "evaluation_metrics": row.evaluation_metrics or {},
        "slice_metrics": row.slice_metrics or {},
    }


def register_candidate(
    db: Session,
    *,
    model_type: ModelType | str,
    scope: str,
    algorithm_version: str,
    feature_schema_version: str,
    artifact_json: Mapping[str, Any],
    user_id: Optional[int] = None,
    label_version: Optional[str] = None,
    calibration_version: Optional[str] = None,
    source_eligibility_watermark: Optional[int] = None,
    effective_sample_size: float = 0.0,
    evaluation_metrics: Optional[Mapping[str, Any]] = None,
    slice_metrics: Optional[Mapping[str, Any]] = None,
    training_window_start: Optional[datetime] = None,
    training_window_end: Optional[datetime] = None,
    model_id: Optional[str] = None,
) -> SchedulingModelRegistry:
    model_type_value = ModelType(model_type).value
    if scope not in ALLOWED_SCOPES:
        raise RegistryError("unsupported model scope")
    if scope == "personal" and user_id is None:
        raise RegistryError("personal models require a user owner")
    if scope != "personal" and user_id is not None:
        raise RegistryError("shared priors cannot carry a user owner")
    if not math.isfinite(float(effective_sample_size)) or not 0 <= float(effective_sample_size) <= 1_000_000:
        raise RegistryError("effective sample size is out of bounds")
    if training_window_start and training_window_end and training_window_start > training_window_end:
        raise RegistryError("training window start cannot exceed end")

    algorithm = _validate_version(algorithm_version, "algorithm_version", required=True)
    feature = _validate_version(feature_schema_version, "feature_schema_version", required=True)
    label = _validate_version(label_version, "label_version")
    calibration = _validate_version(calibration_version, "calibration_version")
    artifact = validate_data_artifact(artifact_json)
    evaluation = _validate_metrics(evaluation_metrics, "evaluation metrics")
    slices = _validate_metrics(slice_metrics, "slice metrics")

    if scope == "personal":
        consent = get_or_create_private_consent(db, int(user_id))
        watermark = int(source_eligibility_watermark or consent.eligibility_watermark)
        if watermark != int(consent.eligibility_watermark):
            raise RegistryError("candidate source watermark is stale")
    else:
        watermark = int(source_eligibility_watermark or 1)
    if watermark < 1:
        raise RegistryError("source eligibility watermark must be positive")

    stable_id = model_id or str(uuid4())
    try:
        UUID(stable_id)
    except (TypeError, ValueError) as exc:
        raise RegistryError("model_id must be a UUID") from exc

    signature = {
        "user_id": user_id,
        "model_type": model_type_value,
        "scope": scope,
        "algorithm_version": algorithm,
        "feature_schema_version": feature,
        "label_version": label,
        "calibration_version": calibration,
        "source_eligibility_watermark": watermark,
        "artifact_json": artifact,
        "evaluation_metrics": evaluation,
        "slice_metrics": slices,
    }
    existing = db.query(SchedulingModelRegistry).filter_by(model_id=stable_id).one_or_none()
    if existing is not None:
        if existing.lifecycle != ModelLifecycle.candidate.value or _row_signature(existing) != signature:
            raise RegistryError("model_id already identifies a different immutable registry entry")
        return existing

    row = SchedulingModelRegistry(
        model_id=stable_id,
        user_id=user_id,
        model_type=model_type_value,
        scope=scope,
        lifecycle=ModelLifecycle.candidate.value,
        algorithm_version=algorithm,
        feature_schema_version=feature,
        label_version=label,
        calibration_version=calibration,
        source_eligibility_watermark=watermark,
        training_window_start=training_window_start,
        training_window_end=training_window_end,
        effective_sample_size=Decimal(str(round(float(effective_sample_size), 4))),
        artifact_json=artifact,
        evaluation_metrics=evaluation,
        slice_metrics=slices,
    )
    db.add(row)
    db.flush()
    return row


def _compatibility_matches(row: SchedulingModelRegistry, compatibility: RegistryCompatibility) -> bool:
    return (
        row.algorithm_version == compatibility.algorithm_version
        and row.feature_schema_version == compatibility.feature_schema_version
        and row.label_version == compatibility.label_version
        and row.calibration_version == compatibility.calibration_version
    )


def move_to_shadow(db: Session, model_id: str, *, reason: str = "evaluation_started") -> SchedulingModelRegistry:
    row = db.query(SchedulingModelRegistry).filter_by(model_id=model_id).with_for_update().one_or_none()
    if row is None:
        raise RegistryError("model not found")
    if row.lifecycle == ModelLifecycle.shadow.value:
        return row
    if row.lifecycle != ModelLifecycle.candidate.value or row.invalidated_at is not None:
        raise RegistryError("only an eligible candidate can enter shadow")
    row.lifecycle = ModelLifecycle.shadow.value
    row.lifecycle_reason = reason[:255]
    db.flush()
    return row


def resolve_serving_model(
    db: Session,
    *,
    user_id: Optional[int],
    model_type: ModelType | str,
    scope: str,
    compatibility: RegistryCompatibility,
) -> RegistryResolution:
    model_type_value = ModelType(model_type).value
    if scope == "personal":
        if user_id is None:
            return RegistryResolution(None, "missing_user")
        consent = get_or_create_private_consent(db, user_id)
        if not consent.operational_personalization_enabled:
            return RegistryResolution(None, "personalization_disabled")
        watermark = int(consent.eligibility_watermark)
    else:
        watermark = None
    rows = db.query(SchedulingModelRegistry).filter(
        SchedulingModelRegistry.user_id.is_(None) if user_id is None else SchedulingModelRegistry.user_id == user_id,
        SchedulingModelRegistry.model_type == model_type_value,
        SchedulingModelRegistry.scope == scope,
        SchedulingModelRegistry.lifecycle == ModelLifecycle.promoted.value,
        SchedulingModelRegistry.invalidated_at.is_(None),
    ).order_by(SchedulingModelRegistry.serving_started_at.desc(), SchedulingModelRegistry.id.desc()).all()
    for row in rows:
        if watermark is not None and int(row.source_eligibility_watermark) != watermark:
            continue
        if _compatibility_matches(row, compatibility):
            try:
                validate_data_artifact(row.artifact_json)
            except RegistryError:
                continue
            return RegistryResolution(row, None)
    return RegistryResolution(None, "no_compatible_promoted_model")


def promote_model(
    db: Session,
    model_id: str,
    *,
    approved_by: str,
    compatibility: RegistryCompatibility,
    failure_injector: Optional[Callable[[], None]] = None,
) -> SchedulingModelRegistry:
    if not approved_by or len(approved_by) > 64:
        raise RegistryError("approved_by is required and bounded")
    now = utc_now_naive()
    with db.begin_nested():
        row = db.query(SchedulingModelRegistry).filter_by(model_id=model_id).with_for_update().one_or_none()
        if row is None:
            raise RegistryError("model not found")
        if row.lifecycle == ModelLifecycle.promoted.value and _compatibility_matches(row, compatibility):
            return row
        if row.lifecycle != ModelLifecycle.shadow.value or row.invalidated_at is not None:
            raise RegistryError("only an eligible shadow model can be promoted")
        if not _compatibility_matches(row, compatibility):
            raise RegistryError("candidate version is incompatible with this serving process")
        validate_data_artifact(row.artifact_json)
        if row.scope == "personal":
            consent = get_or_create_private_consent(db, int(row.user_id))
            if not consent.operational_personalization_enabled:
                raise RegistryError("operational personalization is disabled")
            if int(row.source_eligibility_watermark) != int(consent.eligibility_watermark):
                raise RegistryError("candidate source watermark is stale")

        active_rows = db.query(SchedulingModelRegistry).filter(
            SchedulingModelRegistry.user_id.is_(None) if row.user_id is None else SchedulingModelRegistry.user_id == row.user_id,
            SchedulingModelRegistry.model_type == row.model_type,
            SchedulingModelRegistry.scope == row.scope,
            SchedulingModelRegistry.lifecycle == ModelLifecycle.promoted.value,
            SchedulingModelRegistry.invalidated_at.is_(None),
        ).with_for_update().all()
        prior = max(active_rows, key=lambda item: (item.serving_started_at or item.created_at, item.id)) if active_rows else None
        for active in active_rows:
            active.lifecycle = ModelLifecycle.superseded.value
            active.serving_ended_at = now
            active.lifecycle_reason = f"superseded_by:{row.model_id}"[:255]
        row.fallback_model_id = prior.id if prior is not None else None
        row.lifecycle = ModelLifecycle.promoted.value
        row.serving_started_at = now
        row.serving_ended_at = None
        row.approved_by = approved_by
        row.lifecycle_reason = "promotion_gates_passed"
        if failure_injector is not None:
            failure_injector()
        db.flush()
    return row


def _eligible_fallback(
    db: Session,
    row: SchedulingModelRegistry,
    compatibility: RegistryCompatibility,
) -> Optional[SchedulingModelRegistry]:
    candidates: list[SchedulingModelRegistry] = []
    if row.fallback_model_id is not None:
        linked = db.query(SchedulingModelRegistry).filter_by(id=row.fallback_model_id).with_for_update().one_or_none()
        if linked is not None:
            candidates.append(linked)
    historical = db.query(SchedulingModelRegistry).filter(
        SchedulingModelRegistry.user_id.is_(None) if row.user_id is None else SchedulingModelRegistry.user_id == row.user_id,
        SchedulingModelRegistry.model_type == row.model_type,
        SchedulingModelRegistry.scope == row.scope,
        SchedulingModelRegistry.lifecycle == ModelLifecycle.superseded.value,
        SchedulingModelRegistry.invalidated_at.is_(None),
        SchedulingModelRegistry.id != row.id,
    ).order_by(SchedulingModelRegistry.serving_ended_at.desc(), SchedulingModelRegistry.id.desc()).with_for_update().all()
    candidates.extend(item for item in historical if item not in candidates)
    consent = get_or_create_private_consent(db, int(row.user_id)) if row.scope == "personal" else None
    for candidate in candidates:
        if candidate.invalidated_at is not None or not _compatibility_matches(candidate, compatibility):
            continue
        if consent is not None and int(candidate.source_eligibility_watermark) != int(consent.eligibility_watermark):
            continue
        try:
            validate_data_artifact(candidate.artifact_json)
        except RegistryError:
            continue
        return candidate
    return None


def kill_model(
    db: Session,
    model_id: str,
    *,
    reason: str,
    compatibility: RegistryCompatibility,
) -> RegistryResolution:
    if not reason or len(reason) > 255:
        raise RegistryError("kill reason is required and bounded")
    now = utc_now_naive()
    with db.begin_nested():
        row = db.query(SchedulingModelRegistry).filter_by(model_id=model_id).with_for_update().one_or_none()
        if row is None:
            raise RegistryError("model not found")
        if row.lifecycle == ModelLifecycle.killed.value:
            fallback = _eligible_fallback(db, row, compatibility)
            return RegistryResolution(fallback, "already_killed" if fallback else "prior_fallback")
        was_promoted = row.lifecycle == ModelLifecycle.promoted.value
        if row.lifecycle not in {
            ModelLifecycle.candidate.value,
            ModelLifecycle.shadow.value,
            ModelLifecycle.promoted.value,
        }:
            raise RegistryError("model lifecycle cannot be killed")
        row.lifecycle = ModelLifecycle.killed.value
        row.serving_ended_at = row.serving_ended_at or now
        row.lifecycle_reason = f"killed:{reason}"[:255]
        fallback = _eligible_fallback(db, row, compatibility) if was_promoted else None
        if fallback is not None:
            fallback.lifecycle = ModelLifecycle.promoted.value
            fallback.serving_started_at = now
            fallback.serving_ended_at = None
            fallback.lifecycle_reason = f"rollback_from:{row.model_id}"[:255]
        db.flush()
    return RegistryResolution(fallback, "rolled_back" if fallback else "prior_fallback")
