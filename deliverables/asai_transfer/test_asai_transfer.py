"""Contract tests for student_b/experiments/asai_transfer.py.

Run from the repository root:
  & F:/ChatGPT/upc/.venv/Scripts/python.exe -m unittest \
      deliverables/asai_transfer/test_asai_transfer.py -v

The tests exercise the checks that failed in the first draft (alignment
invariance, score arithmetic, estimator plumbing) and freeze the external
input schemas (Asai pooled prior, DFL penalties, ISSIA clips, extra DFL).
"""
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'student_b' / 'experiments'))
sys.path.insert(0, str(ROOT / 'student_b'))

import asai_transfer as T  # noqa: E402


class TransferContract(unittest.TestCase):
    def test_algebra(self):
        result = T.check_algebra()
        self.assertTrue(result['passed'], result)
        self.assertTrue(result['fixed_frame_matches_velocity_dependent'])

    def test_future_invariance(self):
        result = T.check_future_invariance()
        self.assertTrue(result['passed'], result)
        self.assertTrue(result['fits_identical'])
        self.assertTrue(result['predictions_identical'])
        self.assertTrue(result['score_changed'])

    def test_alignment_invariance(self):
        result = T.check_alignment_invariance()
        self.assertTrue(result['passed'], result)
        self.assertTrue(result['geometry_recovered'])
        self.assertTrue(result['fits_identical'])
        self.assertTrue(result['scores_identical'])

    def test_score_arithmetic(self):
        result = T.check_score_arithmetic()
        self.assertTrue(result['passed'], result)
        self.assertAlmostEqual(result['rmse_cm'], result['expected_rmse_cm'], places=9)
        self.assertAlmostEqual(result['plane_error_cm'],
                               result['expected_plane_error_cm'], places=9)

    def test_aggregates_end_to_end(self):
        result = T.check_aggregate_end_to_end()
        self.assertTrue(result['passed'], result)
        self.assertTrue(result['rows_carry_error_cm'])
        self.assertTrue(result['means_match_rows'])

    def test_estimator_plumbing(self):
        result = T.check_estimator_plumbing()
        self.assertTrue(result['passed'], result)
        self.assertTrue(result['draws_inside_shared_bounds'])
        self.assertLess(result['map_cost'], 1e-6)

    def test_fit_cannot_take_a_future_block(self):
        """`fit_prefix` accepts the prefix only; there is no held-out argument."""
        parameters = list(inspect.signature(T.fit_prefix).parameters)
        self.assertEqual(parameters, ['times', 'points', 'sigma', 'prior',
                                      'prior_params', 'c_seeds'])
        case = T.synth_case()
        with self.assertRaises(TypeError):
            T.fit_prefix(case['fit_times'], case['fit_points'], case['sigma'],
                         'none', None, None, case['future_points'])

    def test_endpoint_ground_rule(self):
        """A rising plane crossing is not discarded by the (absent) ground fraction."""
        import numpy as np
        v0 = np.array([28., 1.2, 2.4])
        frame = T.AF.transverse_frame(v0)
        omega = T.omega_from_c(np.array([.15, -.10]), frame)[0]
        theta = np.r_[np.zeros(3), omega, T.AF.CD][None]
        goal = T.endpoint_draws(np.array([0., 0., .30]), v0, theta, 6.5,
                                T.Config(dt=.005))[0]
        self.assertTrue(np.isfinite(goal).all())


class FrozenInputs(unittest.TestCase):
    def test_pooled_prior_matches_the_archived_fits(self):
        path = ROOT / 'student_b/runs/asai_factorial/results.json'
        prior, meta = T.load_pooled_prior(path)
        self.assertEqual(prior['members'], ['Fig3', 'Sample05', 'Sample12'])
        self.assertGreaterEqual(prior['mag_sd'], .08 - 1e-12)
        self.assertGreaterEqual(prior['vert_sd'], .06 - 1e-12)
        self.assertAlmostEqual(prior['mag_mean'], .1914, places=3)
        self.assertAlmostEqual(prior['vert_mean'], .0330, places=3)
        self.assertEqual(len(meta['fits']), 3)

    def test_dfl_penalty_schema(self):
        cases = T.load_dfl_penalty(ROOT / 'student-a/flight_trajectory_validation_2026-11-07')
        self.assertEqual([c['case'] for c in cases], ['J03WOH', 'J03WR9'])
        for case in cases:
            self.assertEqual(len(case['fit_times']), 3)
            self.assertAlmostEqual(case['spacing'], .04, places=9)
            self.assertIsNotNone(case['target_x'])
            self.assertIsNotNone(case['reference_yz_m'])
            self.assertGreater(case['forward_reach_m'], case['target_x'])
            self.assertEqual(case['alignment'], 'identity_local_frame')

    def test_issia_schema_and_alignment(self):
        cases = T.load_issia(ROOT / 'student_b/runs/issia_A')
        self.assertEqual([c['case'] for c in cases],
                         ['seg_0608_0627', 'seg_1144_1172'])
        for case in cases:
            self.assertEqual(case['alignment'], 'early_forward_axis')
            self.assertAlmostEqual(case['spacing'], .04, places=9)
            self.assertGreater(case['forward_reach_m'], 10.)
            self.assertGreater(case['observed_start_height_m'], .11)

    def test_extra_dfl_schema(self):
        path = (ROOT / 'student-a/additional_flight_data_2026-11-07'
                / 'positions.csv')
        cases = T.load_extra_dfl(path)
        self.assertEqual(len(cases), 11)
        for case in cases:
            self.assertIsNone(case['target_x'])
            self.assertEqual(case['alignment'], 'early_forward_axis')
            self.assertEqual(len(case['fit_times']), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
