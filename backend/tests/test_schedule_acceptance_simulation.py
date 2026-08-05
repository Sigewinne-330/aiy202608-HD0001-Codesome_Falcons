import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_acceptance_simulation import run_acceptance_simulation  # noqa: E402


class ScheduleAcceptanceSimulationTests(unittest.TestCase):
    def test_seeded_report_is_repeatable_and_all_guardrails_hold(self):
        first = run_acceptance_simulation(seed=20260805)
        second = run_acceptance_simulation(seed=20260805)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertTrue(first.all_invariants_passed)
        self.assertEqual(7, len(first.scenarios))
        self.assertTrue(all(item.invariant_checks for item in first.scenarios))

    def test_different_seed_changes_only_synthetic_observations(self):
        first = run_acceptance_simulation(seed=1)
        second = run_acceptance_simulation(seed=2)
        self.assertNotEqual(first.report_hash, second.report_hash)
        self.assertEqual(
            [item.name for item in first.scenarios],
            [item.name for item in second.scenarios],
        )
        self.assertTrue(first.all_invariants_passed and second.all_invariants_passed)


if __name__ == "__main__":
    unittest.main()
