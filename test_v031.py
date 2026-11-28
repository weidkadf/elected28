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

    def test_waves_and_cells_reproduce_published_totals(self):
        self.assertEqual(sorted(self.waves), ['392', '394', '395', '578', '579', '580', '662', '663', '664', '678', '683'])
        for w, v in self.waves.items():
            fr = v['frame_by_party']
            tot = fr['total']
            n = sum(fr[g]['n_weighted'] for g in TO.GROUPS)
            self.assertEqual(n, tot['n_weighted'], w)
            s = sum(fr[g]['n_weighted'] * fr[g]['support'] for g in TO.GROUPS)
            self.assertAlmostEqual(s / n, tot['support'], places=2, msg=w)
            self.assertGreater(fr['residual_other_parties']['n_weighted'], 0)

    def test_turnout_propensity_from_2020_only(self):
        tp = TO.turnout_propensity(self.waves, '2024-04-10')
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

    def test_rewinding_excludes_future_and_same_day_publications(self):
        for cutoff in ('2026-11-11', '2026-11-20'):
            shift, detail = TO.period_shift(self.waves, ['678', '683'], cutoff, 28, 0.89, 0.56)
            self.assertEqual(set(detail), {'678'})
            self.assertAlmostEqual(shift, TO.lv_shift(self.waves['678'], 0.89, 0.56))
        with self.assertRaisesRegex(ValueError, 'no turnout waves available'):
            TO.period_shift(self.waves, ['678', '683'], '2026-10-16', 28, 0.89, 0.56)

    def test_current_independents_lean_check_so_shift_favours_democrats(self):
        self.assertGreater(TO.lv_shift(self.waves['678'], 0.89, 0.56), 0.0)

    def test_kappa_monotone_toward_larger_aligned_bloc(self):
        w = self.waves['678']
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


class PartyCompositionTests(unittest.TestCase):
    """Weekly Gallup party support (incl. weeks without a frame question) sets turnout-group sizes."""
    @classmethod
    def setUpClass(cls):
        cls.waves = TO.load()
        cls.rows = TO.load_party_support()

    def test_tiers_and_shares_sum_to_one(self):
        self.assertTrue(self.rows)
        for r in self.rows:
            self.assertAlmostEqual(sum(r['shares'].values()), 1.0, places=9)
            self.assertGreaterEqual(min(r['shares'].values()), 0.0)
            self.assertNotIn('여론조사꽃', r['pollster'])
        tier = {r['reg_no']: (r['pollster'], r['tier']) for r in self.rows}
        self.assertEqual(tier['17369'], ('gallup', 'level'))
        self.assertEqual(tier['17352'], ('nbs', 'level'))
        self.assertEqual(tier['13158'][1], 'trend')  # Gallup commissioned survey, not Daily Opinion

    def test_includes_weeks_without_frame_question(self):
        comp = TO.party_composition(self.rows, '2026-11-22', 28, include_trend=False)
        gallup = [r for r in comp['reg_nos'] if r in ('17335', '17344', '17353', '17369')]
        self.assertEqual(gallup, ['17335', '17344', '17353', '17369'])  # only 17369 asked the frame question
        self.assertIn('17352', comp['reg_nos'])  # NBS
        self.assertEqual(comp['n_trend'], 0)

    def test_trend_polls_enter_net_of_house_effect(self):
        comp = TO.party_composition(self.rows, '2026-11-22', 28)
        self.assertGreater(comp['n_trend'], 10)
        h = comp['house_effects']['리얼미터|ARS']
        self.assertLess(h['independent'], -0.1)  # ARS finds far fewer 무당층 than Gallup/NBS
        raw = [r for r in self.rows if r['pollster'] == '리얼미터|ARS' and r['reg_no'] in comp['reg_nos']]
        self.assertTrue(raw)
        self.assertLess(max(r['shares']['independent'] for r in raw), comp['shares']['independent'])

    def test_house_effect_uses_only_polls_available_before_cutoff(self):
        cut = '2026-11-22'
        later = [dict(r, reg_no='x' + r['reg_no'], fieldwork_end='2026-11-25', published_at='2026-11-26',
                      shares={'dem': 0.9, 'con': 0.05, 'independent': 0.03, 'residual_other_parties': 0.02}) for r in self.rows[:40]]
        a = TO.party_composition(self.rows, cut, 28)
        b = TO.party_composition(self.rows + later, cut, 28)
        self.assertEqual(a['shares'], b['shares'])
        self.assertEqual(a['house_effects'], b['house_effects'])

    def test_no_lookahead(self):
        comp = TO.party_composition(self.rows, '2026-11-20', 28)  # 17369 published 11-20: excluded on the day
        self.assertNotIn('17369', comp['reg_nos'])
        with self.assertRaises(ValueError):
            TO.party_composition(self.rows, '2023-10-01', 28)  # before the series starts

    def test_crosstab_sizes_reproduced_when_composition_matches_wave(self):
        w = self.waves['683']
        fr = w['frame_by_party']
        comp = {g: fr[g]['n_weighted'] / fr['total']['n_weighted'] for g in TO.GROUPS}
        self.assertAlmostEqual(TO.lv_shift(w, 0.89, 0.56, composition=comp), TO.lv_shift(w, 0.89, 0.56), places=12)

    def test_disabled_flag_restores_crosstab_sizes(self):
        cfg = json.loads((ROOT / 'config/forecast_v050.json').read_text(encoding='utf-8'))
        self.assertTrue(cfg['turnout_adjustment']['party_composition']['enabled'])
        b = {'config': {'half_life_days': 14.0}}; c = {'config': {'half_life_days': 28.0}}
        tp, ti, _ = TO.forecast_propensity(cfg, self.waves)
        off = copy.deepcopy(cfg); off['turnout_adjustment']['party_composition']['enabled'] = False
        bs0, cs0, d0 = TO.forecast_shifts(off, self.waves, b, c, tp, ti, 1.0)
        self.assertNotIn('party_composition', d0)
        ref_b, _ = TO.period_shift(self.waves, cfg['turnout_adjustment']['baseline_waves'], cfg['frame_inputs']['baseline_as_of'], 14.0, tp, ti)
        self.assertAlmostEqual(bs0, ref_b, places=12)
        bs1, cs1, d1 = TO.forecast_shifts(cfg, self.waves, b, c, tp, ti, 1.0)
        self.assertEqual(sorted(d1['party_composition']), ['baseline', 'current'])
        self.assertNotAlmostEqual(cs1, cs0, places=6)


if __name__ == '__main__':
    unittest.main()
