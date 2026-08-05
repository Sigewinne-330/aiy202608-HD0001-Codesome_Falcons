import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.schedule_risk_model import (  # noqa: E402
    RiskEpisode,
    RiskFeatureSnapshot,
    attach_calibration_state,
    evaluate_risk_calibration,
    expand_risk_episodes,
    fit_completion_risk_model,
    predict_completion_by_horizon,
)


class ScheduleRiskModelTests(unittest.TestCase):
    def setUp(self):
        self.start = date(2026, 1, 1)

    def _feature(self, day, *, progress=0.2, effort=180, available_at=None, blocked=False):
        return RiskFeatureSnapshot(
            local_date=day,
            available_at=available_at or day,
            remaining_effort_p50_minutes=effort,
            remaining_effort_p90_minutes=effort * 1.8,
            slack_days=5,
            progress_ratio=progress,
            deferral_count=0,
            projected_energy_ratio=0.7,
            dependency_blocked=blocked,
            split_packet_count=2,
            priority="high",
        )

    def _episode(self, index, *, completed, base=None, progress=0.2):
        base = base or self.start
        snapshots = tuple(
            self._feature(base + timedelta(days=offset), progress=min(1, progress + offset * 0.15))
            for offset in range(4)
        )
        terminal_date = base + timedelta(days=3) if completed else None
        return RiskEpisode(
            episode_id=f"episode-{index}",
            feature_snapshots=snapshots,
            terminal_state="completed" if completed else "unknown",
            terminal_date=terminal_date,
            observation_cutoff=base + timedelta(days=3),
        )

    def test_censored_open_episode_contributes_survival_rows_not_failure_event(self):
        completed = self._episode(1, completed=True)
        censored = self._episode(2, completed=False)
        rows = expand_risk_episodes((completed, censored), cutoff=self.start + timedelta(days=3))
        self.assertEqual(8, len(rows))
        self.assertEqual(1, sum(row.completed_on_date for row in rows))
        self.assertEqual(0, sum(row.completed_on_date for row in rows if row.episode_id == "episode-2"))

        deleted = RiskEpisode(
            episode_id="deleted",
            feature_snapshots=(self._feature(self.start),),
            terminal_state="deleted",
            terminal_date=self.start,
            observation_cutoff=self.start,
        )
        self.assertEqual((), expand_risk_episodes((deleted,), cutoff=self.start))

    def test_insufficient_data_uses_reproducible_prior_fallback(self):
        episodes = (self._episode(1, completed=True), self._episode(2, completed=False))
        first = fit_completion_risk_model(episodes, training_cutoff=self.start + timedelta(days=3))
        second = fit_completion_risk_model(episodes, training_cutoff=self.start + timedelta(days=3))
        self.assertEqual("prior_fallback", first.fit_status)
        self.assertEqual("prior_only", first.calibration_state)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(1, first.completion_event_count)
        self.assertEqual(1, first.censored_episode_count)

    def test_personal_candidate_is_bounded_and_higher_progress_predicts_more_completion(self):
        episodes = tuple(
            self._episode(index, completed=index < 8, progress=0.45 if index < 8 else 0.0)
            for index in range(12)
        )
        cutoff = self.start + timedelta(days=3)
        model = fit_completion_risk_model(episodes, training_cutoff=cutoff)
        self.assertEqual("personal_candidate", model.fit_status)
        self.assertTrue(all(-6 <= value <= 6 for value in model.coefficients.values()))

        future = cutoff + timedelta(days=1)
        high = predict_completion_by_horizon(
            model,
            (self._feature(future, progress=0.9, available_at=cutoff),),
            prediction_cutoff=cutoff,
            horizon_date=future,
        )
        low = predict_completion_by_horizon(
            model,
            (self._feature(future, progress=0.0, available_at=cutoff),),
            prediction_cutoff=cutoff,
            horizon_date=future,
        )
        self.assertGreater(high.probability_by_horizon, low.probability_by_horizon)
        self.assertTrue(0 <= low.probability_by_horizon <= 1)
        self.assertIn("progress", high.dominant_observable_factors)

    def test_future_feature_leakage_and_overlapping_evaluation_are_rejected(self):
        cutoff = self.start + timedelta(days=3)
        model = fit_completion_risk_model((), training_cutoff=cutoff)
        future = cutoff + timedelta(days=1)
        leaking = self._feature(future, available_at=future)
        with self.assertRaises(ValueError):
            predict_completion_by_horizon(
                model,
                (leaking,),
                prediction_cutoff=cutoff,
                horizon_date=future,
            )
        with self.assertRaises(ValueError):
            evaluate_risk_calibration(
                model,
                (),
                evaluation_start=cutoff,
                evaluation_cutoff=cutoff + timedelta(days=1),
            )

        invalid_training = RiskEpisode(
            episode_id="future-leak",
            feature_snapshots=(self._feature(cutoff, available_at=cutoff + timedelta(days=1)),),
            terminal_state="unknown",
            terminal_date=None,
            observation_cutoff=cutoff,
        )
        with self.assertRaises(ValueError):
            expand_risk_episodes((invalid_training,), cutoff=cutoff)

    def test_future_only_calibration_is_bounded_and_attachable(self):
        training_cutoff = self.start + timedelta(days=3)
        training = tuple(self._episode(index, completed=index < 8) for index in range(12))
        model = fit_completion_risk_model(training, training_cutoff=training_cutoff)
        evaluation_start = training_cutoff + timedelta(days=1)
        evaluation = tuple(
            self._episode(index + 100, completed=index < 7, base=evaluation_start)
            for index in range(12)
        )
        metrics = evaluate_risk_calibration(
            model,
            evaluation,
            evaluation_start=evaluation_start,
            evaluation_cutoff=evaluation_start + timedelta(days=3),
        )
        self.assertEqual(48, metrics.row_count)
        self.assertEqual(7, metrics.completion_event_count)
        self.assertTrue(0 <= metrics.brier_score <= 1)
        self.assertTrue(0 <= metrics.expected_calibration_error <= 1)
        self.assertIn(metrics.calibration_state, {"calibrated", "miscalibrated"})
        attached = attach_calibration_state(model, metrics)
        self.assertEqual(metrics.calibration_state, attached.calibration_state)
        self.assertNotEqual(model.model_version, attached.model_version)

    def test_feature_contract_rejects_invalid_ranges(self):
        invalid = self._feature(self.start, progress=1.5)
        with self.assertRaises(ValueError):
            invalid.validate()


if __name__ == "__main__":
    unittest.main()
