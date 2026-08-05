"""Safe, plain-text projection for user-owned role-card imports."""

import re
import secrets
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from models.reminder import ReminderRoleCard
from schemas.reminder import RoleCardCreate


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _source_card(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    nested = payload.get("data")
    if isinstance(nested, dict):
        raw_spec = _text(payload.get("spec")).lower()
        import_format = (
            "chara_card_v2"
            if raw_spec in {"chara_card_v2", "chara_card_v2.0"}
            else "sillytavern-v2"
        )
        return nested, import_format
    if any(key in payload for key in ("first_mes", "mes_example", "alternate_greetings")):
        return payload, "sillytavern-v1"
    return payload, "compact"


def _examples(source: dict[str, Any]) -> list[str]:
    values: list[str] = []
    first = _text(source.get("first_mes"))
    if first:
        values.append(first)
    greetings = source.get("alternate_greetings")
    if isinstance(greetings, list):
        values.extend(_text(item) for item in greetings if _text(item))
    raw_examples = source.get("mes_example")
    if isinstance(raw_examples, str):
        values.extend(
            part.strip()
            for part in re.split(r"\s*<START>\s*", raw_examples)
            if part.strip()
        )
    compact_examples = source.get("example_messages")
    if isinstance(compact_examples, list):
        values.extend(_text(item) for item in compact_examples if _text(item))
    return list(dict.fromkeys(values))[:10]


def normalize_imported_role_card(payload: dict[str, Any]) -> RoleCardCreate:
    """Project supported fields and discard scripts, tools, and extensions.

    SillyTavern V1/V2 exports are accepted as a convenience, but only their
    plain-text identity, personality, prompt, and examples are retained.
    """

    source, import_format = _source_card(payload)
    name = _text(source.get("name"))
    if not name:
        raise ValueError("角色卡必须包含 name 字段")

    description = _text(source.get("description"))
    scenario = _text(source.get("scenario"))
    if scenario:
        description = f"{description}\n场景：{scenario}" if description else f"场景：{scenario}"

    system_prompt = _text(source.get("system_prompt"))
    post_history = _text(source.get("post_history_instructions"))
    if post_history:
        system_prompt = (
            f"{system_prompt}\n{post_history}" if system_prompt else post_history
        )

    raw_slug = _text(source.get("slug")) or _text(source.get("id")) or name
    slug = re.sub(r"[^a-z0-9]+", "-", raw_slug.lower()).strip("-")[:80]
    slug = slug if len(slug) >= 2 else "private-card"
    creator = _text(source.get("creator")) or "User import"
    version = _text(source.get("version")) or _text(source.get("character_version")) or "1.0"
    speaking_style = (
        _text(source.get("speaking_style"))
        or _text(source.get("style"))
        or _text(source.get("creator_notes"))
    )

    # Keep only an audit-friendly format marker. All source extensions,
    # functions, macros, lorebooks, and tool definitions are intentionally
    # discarded before validation and persistence.
    safe_extensions = {"import_format": import_format[:30]}
    return RoleCardCreate(
        slug=slug,
        name=name,
        description=description,
        personality=_text(source.get("personality")),
        speaking_style=speaking_style,
        system_prompt=system_prompt,
        example_messages=_examples(source),
        creator=creator,
        version=version,
        extensions=safe_extensions,
        is_active=True,
    )


def generate_private_role_card_slug(db: Session, seed: str) -> str:
    """Return a unique legacy-compatible slug for a private card."""

    normalized = unicodedata.normalize("NFKD", seed).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "private-card"
    base = base[:68].rstrip("-") or "private-card"
    for _ in range(8):
        candidate = f"{base}-{secrets.token_hex(4)}"
        exists = db.query(ReminderRoleCard.id).filter(ReminderRoleCard.slug == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("无法为私有角色卡生成唯一标识")
