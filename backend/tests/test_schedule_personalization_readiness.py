import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from check_schedule_personalization_readiness import inspect_personalization_schema  # noqa: E402
from database import Base  # noqa: E402
import models  # noqa: F401,E402


class PersonalizationReadinessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    def tearDown(self):
        self.engine.dispose()

    def test_clean_metadata_schema_is_ready(self):
        Base.metadata.create_all(self.engine)
        result = inspect_personalization_schema(self.engine)
        self.assertTrue(result["ok"], result)

    def test_current_schema_without_personalization_reports_only_missing_tables(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE user (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE task (id INTEGER PRIMARY KEY)"))
        result = inspect_personalization_schema(self.engine)
        self.assertFalse(result["ok"])
        self.assertEqual(set(result["missing_tables"]), set(result["checked_tables"]))
        self.assertFalse(result["missing_columns"])
        self.assertFalse(result["missing_indexes"])

    def test_explicit_mysql_migration_is_additive_and_complete(self):
        migration = (BACKEND_DIR / "migrate_schedule_personalization.sql").read_text(encoding="utf-8")
        self.assertNotIn("DROP TABLE", migration.upper())
        self.assertNotIn("DELETE FROM", migration.upper())
        for table_name in inspect_personalization_schema.__globals__["REQUIRED_COLUMNS"]:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS `{table_name}`", migration)
        self.assertLess(
            migration.index("CREATE TABLE IF NOT EXISTS `scheduling_model_registry`"),
            migration.index("CREATE TABLE IF NOT EXISTS `scheduling_model_predictions`"),
        )


if __name__ == "__main__":
    unittest.main()
