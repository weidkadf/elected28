"""v0.3.1 tests: frame-by-party crosstabs and the likely-voter (turnout) adjustment."""
import copy
import json
import sys
import unittest
from pathlib import Path

import turnout as TO

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))


class CrosstabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.waves = TO.load()

    def test_ten_waves_and_cells_reproduce_published_totals(self):
        self.assertEqual(sorted(self.waves), ['392', '394', '395', '578', '579', '580', '662', '663', '664', '678'])
        for w, v in self.waves.items():
            fr = v['frame_by_party']
            tot = fr['total']
            n = sum(fr[g]['n_weighted'] for g in TO.GROUPS)
            self.assertEqual(n, tot['n_weighted'], w)
            s = sum(fr[g]['n_weighted'] * fr[g]['support'] for g in TO.GROUPS)
            self.assertAlmostEqual(s / n, tot['support'], places=2, msg=w)
            self.assertGreater(fr['residual_other_parties']['n_weighted'], 0)

    def test_turnout_propensity_from_2020_only(self):
        tp = TO.turnout_propensity(self.waves)
        self.assertEqual(tp['waves_used'], ['394', '395'])
        self.assertAlmostEqual(tp['tau_partisan'], 0.89, places=3)
        self.assertAlmostEqual(tp['tau_independent'], 0.56, places=3)


class TurnoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.waves = TO.load()

    def test_equal_propensity_means_no_shift(self):
        for w in self.waves.values():
            self.assertAlmostEqual(TO.lv_shift(w, 0.8, 0.8, 1.0), 0.0, places=12)

    def test_current_independents_lean_check_so_shift_favours_democrats(self):
        self.assertGreater(TO.lv_shift(self.waves['678'], 0.89, 0.56), 0.0)

    def test_kappa_monotone_toward_larger_aligned_bloc(self):
        w = self.waves['678']   # Democrat-aligned bloc larger than conservative-aligned bloc
        self.assertGreater(TO.lv_shift(w, 0.89, 0.56, 1.2), TO.lv_shift(w, 0.89, 0.56, 1.0))

    def test_role_alignment_flips_with_government(self):
        w = copy.deepcopy(self.waves['678'])
        q0, _ = TO.lv_q(w, 0.89, 0.56)
        w['governing_party'] = '국민의힘'
        q1, _ = TO.lv_q(w, 0.89, 0.56)
        self.assertAlmostEqual(q0 + q1, 1.0, places=12)


class IntegrationTests(unittest.TestCase):
    def test_forecast_shift_is_uniform_across_regions(self):
        rep = json.loads((ROOT / 'outputs/forecast_v030.json').read_text(encoding='utf-8'))
        fi = rep['frame_inputs']
        net = rep['turnout_adjustment']['net_change_effect_logit']
        for r, v in fi['regional_logit_change_main'].items():
            self.assertAlmostEqual(v - fi['regional_logit_change_no_turnout_adjustment'][r], net, places=12)
        self.assertTrue(rep['turnout_adjustment']['enabled_in_main'])

    def test_backtest_alpha_and_sigmas_unchanged_by_uniform_shift(self):
        bt = json.loads((ROOT / 'outputs/backtest_2020_2024.json').read_text(encoding='utf-8'))
        a, b = bt['fit_intercept_free'], bt['fit_without_turnout_adjustment']
        for k in ('alpha', 'sigma_region', 'sigma_district'):
            self.assertAlmostEqual(a[k], b[k], places=4)
        ta = bt['turnout_adjustment']
        self.assertLess(abs(ta['national_frame_change_with'] - ta['observed_mean_district_change']),
                        abs(ta['national_frame_change_without'] - ta['observed_mean_district_change']))


if __name__ == '__main__':
    unittest.main()
