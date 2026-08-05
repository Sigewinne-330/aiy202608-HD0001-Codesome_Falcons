"""Versioned general task taxonomy and conservative IB cold-start priors.

The values in this module are product defaults, not learned user facts.  They
provide a bounded reference class until eligible personal evidence exists.
Task type, subject, and scope are kept separate so an uncertain quantity cannot
be hidden behind a confident-looking subject or archetype match.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
import unicodedata
from typing import Iterable, Optional

from schemas.schedule_personalization import (
    EFFORT_PRIOR_VERSION,
    TASK_TAXONOMY_VERSION,
    TaskArchetype,
)


LEGACY_TASK_TAXONOMY_VERSION = "scheduling-task-taxonomy.v0"
SUPPORTED_TASK_TAXONOMY_VERSIONS = (
    LEGACY_TASK_TAXONOMY_VERSION,
    TASK_TAXONOMY_VERSION,
)
_NORMAL_QUANTILE_90 = 1.2815515655446004


@dataclass(frozen=True)
class ArchetypeDefinition:
    code: str
    display_name: str
    aliases: tuple[str, ...]
    compatible_units: tuple[str, ...]
    median_active_minutes: int
    log_sigma: float


@dataclass(frozen=True)
class IBSubjectDefinition:
    code: str
    display_name: str
    family: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SubjectResolution:
    status: str
    subject: Optional[str]
    matched_subjects: tuple[str, ...]
    confidence: float
    taxonomy_version: str = TASK_TAXONOMY_VERSION


@dataclass(frozen=True)
class ArchetypeResolution:
    task_archetype: str
    matched_archetypes: tuple[str, ...]
    confidence: float
    provenance: str
    ambiguity: str
    taxonomy_version: str = TASK_TAXONOMY_VERSION


@dataclass(frozen=True)
class TaxonomyMigration:
    task_archetype: str
    from_version: str
    to_version: str
    migrated: bool
    lossy: bool


@dataclass(frozen=True)
class EffortPrior:
    task_archetype: str
    subject: Optional[str]
    matched_subjects: tuple[str, ...]
    p10_active_minutes: int
    p50_active_minutes: int
    p90_active_minutes: int
    log_mean: float
    log_sigma: float
    scope: str
    cold_start: bool
    is_personal: bool
    provenance: str
    fallback_reason: Optional[str]
    taxonomy_version: str = TASK_TAXONOMY_VERSION
    prior_version: str = EFFORT_PRIOR_VERSION


@dataclass(frozen=True)
class _IBPriorProfile:
    base_multiplier: float
    uncertainty_delta: float
    archetype_multipliers: tuple[tuple[str, float], ...] = ()

    def multiplier_for(self, archetype: str) -> float:
        return self.base_multiplier * dict(self.archetype_multipliers).get(archetype, 1.0)


ARCHETYPE_DEFINITIONS: tuple[ArchetypeDefinition, ...] = (
    ArchetypeDefinition("reading", "Reading", ("read", "reading", "阅读", "读书", "lectura", "lire"), ("pages", "chapters"), 60, 0.55),
    ArchetypeDefinition("problem_set", "Problem set", ("problem set", "practice questions", "exercises", "习题", "刷题", "练习题", "题集", "conjunto de problemas"), ("problems", "questions"), 90, 0.65),
    ArchetypeDefinition("exam_preparation", "Exam preparation", ("exam prep", "exam preparation", "revise for exam", "study for exam", "备考", "复习考试", "考试复习", "期末考试", "模拟考"), ("topics", "papers"), 180, 0.70),
    ArchetypeDefinition("research", "Research", ("research", "literature review", "source search", "资料检索", "研究", "文献综述", "recherche", "investigación"), ("sources", "papers"), 150, 0.75),
    ArchetypeDefinition("essay_outline", "Essay outline", ("essay outline", "outline essay", "论文提纲", "作文提纲", "写提纲", "plan de ensayo"), ("sections", "arguments"), 75, 0.60),
    ArchetypeDefinition("essay_draft", "Essay draft", ("essay draft", "first draft", "draft essay", "write essay", "论文初稿", "作文初稿", "写论文", "写作文", "borrador de ensayo"), ("words", "sections"), 180, 0.75),
    ArchetypeDefinition("essay_revision", "Essay revision", ("revise essay", "edit draft", "proofread", "论文修改", "修改初稿", "润色", "校对", "revisión de ensayo"), ("words", "sections"), 90, 0.60),
    ArchetypeDefinition("laboratory", "Laboratory work", ("laboratory", "lab work", "experiment", "实验", "实验室", "实验数据", "laboratorio"), ("runs", "samples"), 180, 0.70),
    ArchetypeDefinition("presentation", "Presentation", ("presentation", "slides", "speech", "演示", "幻灯片", "做汇报", "口头报告", "presentación"), ("slides", "minutes"), 120, 0.65),
    ArchetypeDefinition("long_project", "Long project", ("long project", "coursework project", "capstone", "长期项目", "大项目", "课程项目", "proyecto largo"), ("milestones", "deliverables"), 240, 0.85),
    ArchetypeDefinition("memorization", "Memorization", ("memorize", "flashcards", "vocabulary review", "背诵", "记忆", "背单词", "闪卡", "memorizar"), ("items", "cards"), 60, 0.65),
    ArchetypeDefinition("creative", "Creative production", ("creative work", "design", "compose", "draw", "创作", "设计", "绘画", "作曲", "创意制作"), ("pieces", "iterations"), 120, 0.75),
    ArchetypeDefinition("administration", "Administration", ("administration", "submit form", "upload", "email teacher", "行政", "填表", "提交表格", "上传文件", "发邮件"), ("actions", "forms"), 30, 0.55),
    ArchetypeDefinition("mixed", "Mixed work", ("mixed task", "multi-stage task", "综合任务", "混合任务", "多阶段任务"), ("stages",), 180, 0.90),
    ArchetypeDefinition("unknown", "Unknown work", (), (), 120, 1.00),
)


IB_SUBJECT_DEFINITIONS: tuple[IBSubjectDefinition, ...] = (
    IBSubjectDefinition("mathematics", "Mathematics", "quantitative", ("mathematics", "math", "maths", "数学", "matemáticas", "matematicas", "analysis and approaches", "applications and interpretation", "math aa", "math ai")),
    IBSubjectDefinition("physics", "Physics", "experimental_science", ("physics", "物理", "física", "fisica", "physique")),
    IBSubjectDefinition("chemistry", "Chemistry", "experimental_science", ("chemistry", "化学", "química", "quimica", "chimie")),
    IBSubjectDefinition("biology", "Biology", "experimental_science", ("biology", "生物", "生物学", "biología", "biologia", "biologie")),
    IBSubjectDefinition("environmental_systems_societies", "Environmental systems and societies", "experimental_science", ("environmental systems and societies", "ess", "环境系统与社会", "环境科学")),
    IBSubjectDefinition("computer_science", "Computer science", "quantitative", ("computer science", "computing", "计算机科学", "计算机", "informática", "informatica")),
    IBSubjectDefinition("economics", "Economics", "humanities", ("economics", "经济", "经济学", "economía", "economia", "économie", "economie")),
    IBSubjectDefinition("business_management", "Business management", "humanities", ("business management", "business", "商业管理", "商管", "gestión empresarial", "gestion empresarial")),
    IBSubjectDefinition("psychology", "Psychology", "humanities", ("psychology", "心理学", "psicología", "psicologia", "psychologie")),
    IBSubjectDefinition("history", "History", "humanities", ("history", "历史", "historia", "histoire")),
    IBSubjectDefinition("geography", "Geography", "humanities", ("geography", "地理", "geografía", "geografia", "géographie", "geographie")),
    IBSubjectDefinition("global_politics", "Global politics", "humanities", ("global politics", "politics", "全球政治", "政治学", "política global", "politica global")),
    IBSubjectDefinition("philosophy", "Philosophy", "humanities", ("philosophy", "哲学", "filosofía", "filosofia", "philosophie")),
    IBSubjectDefinition("english", "English", "language", ("english a", "english b", "english", "英语", "inglés", "ingles", "anglais")),
    IBSubjectDefinition("chinese", "Chinese", "language", ("chinese a", "chinese b", "chinese", "中文", "汉语", "中国语言文学")),
    IBSubjectDefinition("language_acquisition", "Language acquisition", "language", ("language acquisition", "second language", "外语", "语言习得", "语言学习")),
    IBSubjectDefinition("visual_arts", "Visual arts", "arts", ("visual arts", "art", "视觉艺术", "美术", "artes visuales")),
    IBSubjectDefinition("music", "Music", "arts", ("music", "音乐", "música", "musica", "musique")),
    IBSubjectDefinition("theatre", "Theatre", "arts", ("theatre", "theater", "戏剧", "théâtre", "teatro")),
    IBSubjectDefinition("film", "Film", "arts", ("film", "电影", "cinema", "cine")),
    IBSubjectDefinition("theory_of_knowledge", "Theory of knowledge", "core", ("theory of knowledge", "tok", "知识论", "认识论")),
    IBSubjectDefinition("extended_essay", "Extended essay", "core", ("extended essay", "ee", "拓展论文", "扩展论文")),
    IBSubjectDefinition("creativity_activity_service", "Creativity, activity, service", "core", ("creativity activity service", "cas", "创造、活动与服务", "创造活动服务")),
)


_FAMILY_PRIOR_PROFILES = {
    "quantitative": _IBPriorProfile(1.05, 0.03, (("problem_set", 1.15), ("exam_preparation", 1.10))),
    "experimental_science": _IBPriorProfile(1.05, 0.05, (("laboratory", 1.25), ("research", 1.15))),
    "humanities": _IBPriorProfile(1.05, 0.04, (("research", 1.10), ("essay_draft", 1.15), ("essay_revision", 1.08))),
    "language": _IBPriorProfile(1.00, 0.04, (("reading", 1.10), ("essay_draft", 1.10), ("memorization", 1.10))),
    "arts": _IBPriorProfile(1.05, 0.08, (("creative", 1.25), ("presentation", 1.10), ("long_project", 1.15))),
    "core": _IBPriorProfile(1.10, 0.08, (("research", 1.15), ("essay_draft", 1.15), ("long_project", 1.25))),
}

_SUBJECT_PROFILE_OVERRIDES = {
    "theory_of_knowledge": _IBPriorProfile(1.10, 0.10, (("essay_outline", 1.15), ("essay_draft", 1.25), ("presentation", 1.10))),
    "extended_essay": _IBPriorProfile(1.15, 0.12, (("research", 1.25), ("essay_draft", 1.25), ("long_project", 1.35))),
    "creativity_activity_service": _IBPriorProfile(1.00, 0.10, (("creative", 1.15), ("administration", 1.10), ("long_project", 1.15))),
}

_LEGACY_ARCHETYPE_CODES = {
    "read": "reading",
    "practice": "problem_set",
    "problem": "problem_set",
    "exam": "exam_preparation",
    "essay": "essay_draft",
    "outline": "essay_outline",
    "revision": "essay_revision",
    "lab": "laboratory",
    "slides": "presentation",
    "project": "long_project",
    "memorise": "memorization",
    "memorize": "memorization",
    "admin": "administration",
    "other": "unknown",
}

_ARCHETYPE_BY_CODE = {item.code: item for item in ARCHETYPE_DEFINITIONS}
_SUBJECT_BY_CODE = {item.code: item for item in IB_SUBJECT_DEFINITIONS}
_MIXED_MARKERS = (" and ", " & ", " plus ", " then ", "并", "以及", "然后", "与", "和")


def _normalize_text(value: Optional[str]) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(character for character in unicodedata.normalize("NFKD", text) if not unicodedata.combining(character))
    text = re.sub(r"[_/|,;:()\[\]{}]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_alias(text: str, alias: str) -> bool:
    normalized_alias = _normalize_text(alias)
    if not normalized_alias:
        return False
    if any("\u4e00" <= character <= "\u9fff" for character in normalized_alias):
        return normalized_alias in text
    return re.search(rf"(?<![\w]){re.escape(normalized_alias)}(?![\w])", text) is not None


def _matching_codes(text: str, definitions: Iterable[object]) -> dict[str, int]:
    matches: dict[str, int] = {}
    for definition in definitions:
        matched_aliases = [alias for alias in definition.aliases if _contains_alias(text, alias)]
        if matched_aliases:
            matches[definition.code] = max(len(_normalize_text(alias)) for alias in matched_aliases)
    return matches


def normalize_ib_subject(value: Optional[str]) -> SubjectResolution:
    text = _normalize_text(value)
    if not text:
        return SubjectResolution("unknown", None, (), 0.0)
    if text in _SUBJECT_BY_CODE:
        return SubjectResolution("recognized", text, (text,), 1.0)
    matches = _matching_codes(text, IB_SUBJECT_DEFINITIONS)
    ordered = tuple(sorted(matches, key=lambda code: (-matches[code], code)))
    if not ordered:
        return SubjectResolution("unknown", None, (), 0.0)
    if len(ordered) > 1:
        return SubjectResolution("mixed", None, tuple(sorted(ordered)), 0.55)
    return SubjectResolution("recognized", ordered[0], ordered, 0.9)


def migrate_archetype_code(
    value: str,
    *,
    from_version: str,
    to_version: str = TASK_TAXONOMY_VERSION,
) -> TaxonomyMigration:
    if from_version not in SUPPORTED_TASK_TAXONOMY_VERSIONS:
        raise ValueError("unsupported source taxonomy version")
    if to_version != TASK_TAXONOMY_VERSION:
        raise ValueError("unsupported target taxonomy version")
    normalized = _normalize_text(value).replace(" ", "_")
    if from_version == TASK_TAXONOMY_VERSION:
        code = normalized if normalized in _ARCHETYPE_BY_CODE else TaskArchetype.unknown.value
        return TaxonomyMigration(code, from_version, to_version, False, code != normalized)
    code = _LEGACY_ARCHETYPE_CODES.get(normalized, normalized)
    if code not in _ARCHETYPE_BY_CODE:
        code = TaskArchetype.unknown.value
    return TaxonomyMigration(code, from_version, to_version, True, code == TaskArchetype.unknown.value and normalized != "unknown")


def normalize_task_archetype(
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    structured_kind: Optional[str] = None,
    structured_taxonomy_version: str = TASK_TAXONOMY_VERSION,
) -> ArchetypeResolution:
    if structured_kind:
        try:
            migration = migrate_archetype_code(
                structured_kind,
                from_version=structured_taxonomy_version,
            )
        except ValueError:
            return ArchetypeResolution("unknown", (), 0.0, "unsupported_taxonomy", "high")
        if migration.task_archetype != "unknown":
            return ArchetypeResolution(
                migration.task_archetype,
                (migration.task_archetype,),
                1.0 if not migration.migrated else 0.95,
                "structured" if not migration.migrated else "migrated_structured",
                "low",
            )

    text = _normalize_text(" ".join(part for part in (title, description) if part))
    matches = _matching_codes(text, (item for item in ARCHETYPE_DEFINITIONS if item.aliases))
    ordered = tuple(sorted(matches, key=lambda code: (-matches[code], code)))
    if not ordered:
        return ArchetypeResolution("unknown", (), 0.0, "product_default", "high")
    if "mixed" in ordered:
        return ArchetypeResolution("mixed", tuple(sorted(set(ordered))), 0.9, "deterministic_alias", "high")
    if len(ordered) > 1 and (any(marker in f" {text} " for marker in _MIXED_MARKERS) or matches[ordered[0]] == matches[ordered[1]]):
        return ArchetypeResolution("mixed", tuple(sorted(ordered)), 0.6, "deterministic_alias", "high")
    return ArchetypeResolution(ordered[0], ordered, 0.85, "deterministic_alias", "medium" if len(ordered) > 1 else "low")


def _rounded_minutes(value: float) -> int:
    return int(max(5, min(2_880, round(value / 5.0) * 5)))


def resolve_effort_prior(
    *,
    task_archetype: str,
    subject: Optional[str] = None,
    taxonomy_version: str = TASK_TAXONOMY_VERSION,
) -> EffortPrior:
    try:
        migration = migrate_archetype_code(task_archetype, from_version=taxonomy_version)
    except ValueError:
        migration = TaxonomyMigration("unknown", taxonomy_version, TASK_TAXONOMY_VERSION, True, True)
        version_fallback = True
    else:
        version_fallback = False

    archetype = migration.task_archetype
    definition = _ARCHETYPE_BY_CODE[archetype]
    subject_resolution = normalize_ib_subject(subject)
    multiplier = 1.0
    sigma = definition.log_sigma
    scope = "general_archetype"
    fallback_reason: Optional[str] = None
    resolved_subject = subject_resolution.subject

    if version_fallback:
        archetype = "unknown"
        definition = _ARCHETYPE_BY_CODE[archetype]
        sigma = definition.log_sigma
        scope = "general_unknown"
        fallback_reason = "unsupported_taxonomy_version"
    elif archetype == "unknown":
        scope = "general_unknown"
        fallback_reason = "unknown_task_archetype"
        resolved_subject = None
    elif archetype == "mixed":
        scope = "general_mixed_task"
        fallback_reason = "mixed_task_archetype"
        sigma += 0.15
        resolved_subject = None
    elif subject_resolution.status == "mixed":
        scope = "general_mixed_subject"
        fallback_reason = "mixed_subject"
        sigma += 0.15
        resolved_subject = None
    elif subject_resolution.status == "unknown":
        scope = "general_archetype"
        fallback_reason = "unknown_or_non_ib_subject" if subject else "subject_not_provided"
        resolved_subject = None
    else:
        subject_definition = _SUBJECT_BY_CODE[subject_resolution.subject]
        profile = _SUBJECT_PROFILE_OVERRIDES.get(subject_definition.code, _FAMILY_PRIOR_PROFILES[subject_definition.family])
        multiplier = profile.multiplier_for(archetype)
        sigma = min(1.25, sigma + profile.uncertainty_delta)
        scope = "ib_subject_archetype"

    median = definition.median_active_minutes * multiplier
    log_mean = math.log(max(5.0, median))
    p10 = _rounded_minutes(math.exp(log_mean - _NORMAL_QUANTILE_90 * sigma))
    p50 = _rounded_minutes(math.exp(log_mean))
    p90 = _rounded_minutes(math.exp(log_mean + _NORMAL_QUANTILE_90 * sigma))
    return EffortPrior(
        task_archetype=archetype,
        subject=resolved_subject,
        matched_subjects=subject_resolution.matched_subjects,
        p10_active_minutes=min(p10, p50),
        p50_active_minutes=p50,
        p90_active_minutes=max(p50, p90),
        log_mean=round(log_mean, 8),
        log_sigma=round(sigma, 8),
        scope=scope,
        cold_start=True,
        is_personal=False,
        provenance="versioned_product_prior",
        fallback_reason=fallback_reason,
    )


def taxonomy_manifest(version: str = TASK_TAXONOMY_VERSION) -> dict:
    if version != TASK_TAXONOMY_VERSION:
        raise ValueError("only the current taxonomy has a serving manifest")
    return {
        "taxonomy_version": TASK_TAXONOMY_VERSION,
        "prior_version": EFFORT_PRIOR_VERSION,
        "archetypes": [asdict(item) for item in ARCHETYPE_DEFINITIONS],
        "ib_subjects": [asdict(item) for item in IB_SUBJECT_DEFINITIONS],
        "legacy_versions": [LEGACY_TASK_TAXONOMY_VERSION],
    }


def taxonomy_fingerprint(version: str = TASK_TAXONOMY_VERSION) -> str:
    payload = json.dumps(taxonomy_manifest(version), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_taxonomy() -> tuple[str, ...]:
    issues: list[str] = []
    archetype_codes = [item.code for item in ARCHETYPE_DEFINITIONS]
    if set(archetype_codes) != {item.value for item in TaskArchetype}:
        issues.append("archetype definitions do not match TaskArchetype enum")
    if len(archetype_codes) != len(set(archetype_codes)):
        issues.append("duplicate archetype code")
    subject_codes = [item.code for item in IB_SUBJECT_DEFINITIONS]
    if len(subject_codes) != len(set(subject_codes)):
        issues.append("duplicate IB subject code")
    for item in ARCHETYPE_DEFINITIONS:
        if item.median_active_minutes <= 0 or not 0.1 <= item.log_sigma <= 1.5:
            issues.append(f"invalid prior bounds for {item.code}")
    for profile in tuple(_FAMILY_PRIOR_PROFILES.values()) + tuple(_SUBJECT_PROFILE_OVERRIDES.values()):
        if not 0.5 <= profile.base_multiplier <= 2.0 or not 0 <= profile.uncertainty_delta <= 0.5:
            issues.append("IB profile outside bounded range")
        if any(code not in _ARCHETYPE_BY_CODE or not 0.5 <= value <= 2.0 for code, value in profile.archetype_multipliers):
            issues.append("IB archetype profile outside taxonomy or bounded range")
    return tuple(issues)


_VALIDATION_ISSUES = validate_taxonomy()
if _VALIDATION_ISSUES:
    raise RuntimeError("invalid scheduling taxonomy: " + "; ".join(_VALIDATION_ISSUES))
