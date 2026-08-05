import json
import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from schemas.schedule_personalization import (  # noqa: E402
    EFFORT_PRIOR_VERSION,
    TASK_TAXONOMY_VERSION,
    TaskArchetype,
    TaskArchetypeHypothesis,
)
from services.schedule_taxonomy import (  # noqa: E402
    ARCHETYPE_DEFINITIONS,
    LEGACY_TASK_TAXONOMY_VERSION,
    migrate_archetype_code,
    normalize_ib_subject,
    normalize_task_archetype,
    resolve_effort_prior,
    taxonomy_fingerprint,
    taxonomy_manifest,
    validate_taxonomy,
)


class ScheduleTaxonomyTests(unittest.TestCase):
    def test_manifest_is_complete_bounded_versioned_and_stable(self):
        manifest = taxonomy_manifest()
        self.assertEqual(TASK_TAXONOMY_VERSION, manifest["taxonomy_version"])
        self.assertEqual(EFFORT_PRIOR_VERSION, manifest["prior_version"])
        self.assertEqual({item.value for item in TaskArchetype}, {item["code"] for item in manifest["archetypes"]})
        self.assertEqual((), validate_taxonomy())
        self.assertEqual(64, len(taxonomy_fingerprint()))
        self.assertEqual(taxonomy_fingerprint(), taxonomy_fingerprint())
        self.assertLess(len(json.dumps(manifest, ensure_ascii=False).encode("utf-8")), 65_536)
        self.assertTrue(all(0 < item.median_active_minutes <= 2_880 for item in ARCHETYPE_DEFINITIONS))

    def test_multilingual_subject_fixtures_and_mixed_unknown_fallback(self):
        fixtures = {
            "IB Physics HL": "physics",
            "化学 IA": "chemistry",
            "Economía": "economics",
            "Math AA": "mathematics",
            "知识论 TOK": "theory_of_knowledge",
        }
        for raw, expected in fixtures.items():
            with self.subTest(raw=raw):
                resolution = normalize_ib_subject(raw)
                self.assertEqual("recognized", resolution.status)
                self.assertEqual(expected, resolution.subject)
        mixed = normalize_ib_subject("Physics 与 Chemistry 综合项目")
        self.assertEqual("mixed", mixed.status)
        self.assertEqual(("chemistry", "physics"), mixed.matched_subjects)
        self.assertEqual("unknown", normalize_ib_subject("Robotics Studio").status)

    def test_multilingual_archetype_fixtures_and_mixed_unknown_fallback(self):
        fixtures = {
            "完成论文初稿": "essay_draft",
            "复习期末考试": "exam_preparation",
            "Conjunto de problemas 5": "problem_set",
            "Upload the consent form": "administration",
        }
        for title, expected in fixtures.items():
            with self.subTest(title=title):
                resolution = normalize_task_archetype(title=title)
                self.assertEqual(expected, resolution.task_archetype)
                self.assertGreater(resolution.confidence, 0)
        mixed = normalize_task_archetype(title="阅读两章并制作演示")
        self.assertEqual("mixed", mixed.task_archetype)
        self.assertEqual(("presentation", "reading"), mixed.matched_archetypes)
        unknown = normalize_task_archetype(title="Build a new quantum widget")
        self.assertEqual("unknown", unknown.task_archetype)
        self.assertEqual("high", unknown.ambiguity)

    def test_prior_hierarchy_is_conservative_and_never_personal(self):
        ib_prior = resolve_effort_prior(task_archetype="essay_draft", subject="Economics")
        self.assertEqual("ib_subject_archetype", ib_prior.scope)
        self.assertEqual("economics", ib_prior.subject)
        self.assertTrue(ib_prior.cold_start)
        self.assertFalse(ib_prior.is_personal)
        self.assertLess(ib_prior.p10_active_minutes, ib_prior.p50_active_minutes)
        self.assertLess(ib_prior.p50_active_minutes, ib_prior.p90_active_minutes)

        general = resolve_effort_prior(task_archetype="essay_draft", subject="Robotics")
        self.assertEqual("general_archetype", general.scope)
        self.assertEqual("unknown_or_non_ib_subject", general.fallback_reason)
        self.assertIsNone(general.subject)

        unknown = resolve_effort_prior(task_archetype="unknown", subject="Physics")
        self.assertEqual("general_unknown", unknown.scope)
        self.assertEqual("unknown_task_archetype", unknown.fallback_reason)
        self.assertIsNone(unknown.subject)
        self.assertGreaterEqual(unknown.p90_active_minutes, unknown.p50_active_minutes * 3)

        mixed = resolve_effort_prior(task_archetype="research", subject="Physics and Chemistry")
        self.assertEqual("general_mixed_subject", mixed.scope)
        self.assertEqual("mixed_subject", mixed.fallback_reason)
        self.assertGreater(mixed.log_sigma, general.log_sigma)

    def test_taxonomy_migration_preserves_known_values_and_degrades_unknowns(self):
        migrated = migrate_archetype_code("essay", from_version=LEGACY_TASK_TAXONOMY_VERSION)
        self.assertEqual("essay_draft", migrated.task_archetype)
        self.assertTrue(migrated.migrated)
        self.assertFalse(migrated.lossy)

        identity = migrate_archetype_code("laboratory", from_version=TASK_TAXONOMY_VERSION)
        self.assertEqual("laboratory", identity.task_archetype)
        self.assertFalse(identity.migrated)

        novel = migrate_archetype_code("simulation_build", from_version=LEGACY_TASK_TAXONOMY_VERSION)
        self.assertEqual("unknown", novel.task_archetype)
        self.assertTrue(novel.lossy)
        with self.assertRaises(ValueError):
            migrate_archetype_code("essay_draft", from_version="scheduling-task-taxonomy.v99")

        safe = resolve_effort_prior(
            task_archetype="essay_draft",
            subject="Economics",
            taxonomy_version="scheduling-task-taxonomy.v99",
        )
        self.assertEqual("general_unknown", safe.scope)
        self.assertEqual("unsupported_taxonomy_version", safe.fallback_reason)

    def test_hypothesis_serializes_taxonomy_lineage(self):
        payload = TaskArchetypeHypothesis(task_archetype="reading").model_dump(mode="json")
        self.assertEqual(TASK_TAXONOMY_VERSION, payload["taxonomy_version"])


if __name__ == "__main__":
    unittest.main()
