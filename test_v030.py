"""v0.3.0 tests: aggregator, partial backtest, sigma(d), alpha curve, prior, release tooling."""
import copy
import json
import math
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

import frame_aggregator as FA
import forecast_v030 as F
import model as M

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_2020_2024 as B  # noqa: E402
import estimate_fundamentals_prior as FP  # noqa: E402


def poll(pid, pollster, end, pub, s, c, n=1000, mode='CATI_live_interview', wc='A_support_check'):
    return {'poll_id': pid, 'pollster': pollster, 'fieldwork_end': end, 'published_at': pub, 'sample_size': n,
            'mode': mode, 'wording_class': wc, 'scope': 'national', 'shares': {'support': s, 'check': c}}


class AggregatorTests(unittest.TestCase):
    def test_same_day_and_future_publication_excluded(self):
        ps = [poll('a', 'X', '2026-10-01', '2026-10-02', .4, .5), poll('b', 'Y', '2026-10-04', '2026-10-05', .3, .6)]
        agg = FA.aggregate(ps, '2026-10-05', 'support')
        self.assertEqual([p['poll_id'] for p in agg['polls_used']], ['a'])

    def test_role_flip_of_democratic_coordinate(self):
        p = poll('a', 'X', '2024-03-01', '2024-03-02', .4, .5)
        self.assertAlmostEqual(FA.dem_coordinate(p, 'support')[0], .4 / .9)
        self.assertAlmostEqual(FA.dem_coordinate(p, 'check')[0], .5 / .9)

    def test_repeated_releases_cannot_raise_pollster_weight(self):
        one = [poll('a', 'X', '2026-10-10', '2026-10-11', .4, .5), poll('z', 'Y', '2026-10-10', '2026-10-11', .3, .6)]
        many = one + [poll(f'a{i}', 'X', '2026-10-10', '2026-10-11', .4, .5) for i in range(5)]
        w1 = FA.aggregate(one, '2026-10-20', 'support')['pollsters']['X']['weight']
        w2 = FA.aggregate(many, '2026-10-20', 'support')['pollsters']['X']['weight']
        self.assertAlmostEqual(w1, w2)

    def test_recency_decay_halves_at_half_life(self):
        ps = [poll('a', 'X', '2026-10-01', '2026-10-02', .4, .5)]
        w = FA.aggregate(ps, '2026-10-29', 'support', {'half_life_days': 28.0})['pollsters']['X']['recency_latest']
        self.assertAlmostEqual(w, 0.5)

    def test_house_effects_centred_and_shrunk(self):
        ps = [poll('a', 'X', '2026-10-10', '2026-10-11', .40, .50), poll('b', 'Y', '2026-10-11', '2026-10-12', .30, .60)]
        h = FA.aggregate(ps, '2026-10-20', 'support')['house_effects']
        hx, hy = h['X']['house_effect_logit_centred'], h['Y']['house_effect_logit_centred']
        self.assertAlmostEqual(hx + hy, 0.0)
        raw = math.log((.4 / .9) / (.5 / .9)) - math.log((.3 / .9) / (.6 / .9))
        self.assertLess(abs(hx), abs(raw))

    def test_judgment_wording_excluded_from_main(self):
        ps = [poll('a', 'X', '2026-10-10', '2026-10-11', .4, .5), poll('b', 'Y', '2026-10-10', '2026-10-11', .1, .8, wc='B_judgment')]
        main = FA.aggregate(ps, '2026-10-20', 'support')
        self.assertEqual([p['poll_id'] for p in main['polls_used']], ['a'])
        sens = FA.aggregate(ps, '2026-10-20', 'support', {'wording_classes': ['A_support_check', 'B_judgment']})
        self.assertEqual(len(sens['polls_used']), 2)

    def test_suppressed_region_falls_back_to_national(self):
        nat = [poll('n', 'G', '2026-10-15', '2026-10-16', .34, .47)]
        reg = [{**nat[0], 'poll_id': 'r', 'scope': '제주', 'shares': {}, 'suppressed': True}]
        dev = FA.regional_deviations(nat, reg, '2026-11-05', 'support', 400)
        self.assertEqual(dev['제주']['deviation_logit'], 0.0)
        self.assertIn('fallback', dev['제주']['status'])

    def test_real_current_aggregate_uses_only_pre_asof_A_class(self):
        cfg = json.loads((ROOT / 'config/forecast_v030.json').read_text(encoding='utf-8'))
        agg, _ = F.current_frames(cfg, ['A_support_check'])
        self.assertEqual({p['poll_id'] for p in agg['polls_used']},
                         {'gallup_678_frame_national', 'hangil_20261026_frame_national'})


class BacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.excluded, cls.xs, cls.y, cls.x, cls.g, _ = B.run()

    def test_sample_counts(self):
        self.assertEqual(len(self.rows) + len(self.excluded), 171)
        self.assertEqual(len(self.rows), 155)
        self.assertEqual(int(B.robust_mask(self.rows).sum()), 149)

    def test_only_pre_election_frames_used(self):
        for year in (2020, 2024):
            _, agg, _ = B.frame_coordinates(year)
            for p in agg['polls_used']:
                self.assertLess(p['fieldwork_end'], B.ELECTION[year])

    def test_fit_recovers_synthetic_alpha(self):
        rng = np.random.default_rng(1)
        scopes = np.array(sorted(set(self.g)))
        xr = dict(zip(scopes, np.linspace(-0.6, 0.6, len(scopes))))
        g = np.repeat(scopes, 40)
        x = np.array([xr[s] for s in g])
        ur = dict(zip(scopes, rng.normal(0, 0.05, len(scopes))))
        y = 0.7 * x + np.array([ur[s] for s in g]) + rng.normal(0, 0.2, len(g))
        f = B.fit(y, x, g)
        self.assertAlmostEqual(f['alpha'], 0.7, delta=0.2)
        self.assertAlmostEqual(f['sigma_district'], 0.2, delta=0.03)

    def test_published_backtest_reports_alpha_not_identified(self):
        bt = json.loads((ROOT / 'outputs/backtest_2020_2024.json').read_text(encoding='utf-8'))
        self.assertFalse(bt['alpha_identified'])
        self.assertIn('turnout weighting groups only', bt['party_support_scope'])
        self.assertEqual(bt['geography'], 'same_statutory_text_unverified_geometry')


class ForecastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads((ROOT / 'config/forecast_v030.json').read_text(encoding='utf-8'))
        cls.D = M.read_baseline(ROOT / 'data/baseline_2024.csv')
        cls.sim = F.Simulator(cls.D, 400, 3, M.REGIONAL_SCOPE_MEMBERS)
        cls.change = F.legacy_single_wave(cls.cfg)

    def test_zero_change_zero_noise_restores_2024(self):
        r = self.sim.run(0.0, self.change, 0, 0, 0)
        self.assertEqual(int(r['dem_seats'][0]), 161)

    def test_legacy_inputs_equal_v023_engine(self):
        P = json.loads((ROOT / 'data/polls.json').read_text(encoding='utf-8'))
        C = json.loads((ROOT / 'config/frame_comparison.json').read_text(encoding='utf-8'))
        sc, _ = M.matched_frame_scenarios(P, C)
        for s, ms in M.REGIONAL_SCOPE_MEMBERS.items():
            for m in ms:
                self.assertAlmostEqual(self.change[s], sc[0]['regional_frame_logit_change'][m], places=12)

    def test_pending_never_allocated_and_seats_conserved(self):
        r = self.sim.run(0.5, self.change, .2, .1, .2)
        self.assertEqual(len(self.sim.pending), 9)
        self.assertTrue(np.all(r['dem_seats'] + r['con_seats'] + r['other_seats'] == 245))

    def test_sigma_national_form(self):
        s = {'national_d0': .12, 'tau': .01, 'd_backtest': 13}
        self.assertEqual(F.sigma_national(0, 500, s), .12)
        self.assertGreater(F.sigma_national(1, 500, s), F.sigma_national(1, 100, s))
        self.assertGreater(F.sigma_national(1, 500, s), F.sigma_national(.5, 500, s))
        self.assertAlmostEqual(F.sigma_national(1, 13, s), .12)

    def test_published_curve_monotone_and_thresholds_ordered(self):
        rep = json.loads((ROOT / 'outputs/forecast_v030.json').read_text(encoding='utf-8'))
        c = rep['scenarios']['main_aggregated_sigma_d']['curve']
        dm = [p['dem']['mean'] for p in c]
        self.assertTrue(all(a >= b for a, b in zip(dm, dm[1:])))
        t = rep['headline']['majority_thresholds_main']['dem_loses_majority_alpha_bounds']
        self.assertLessEqual(t['pending_9_all_non_dem'], t['pending_9_all_dem'])
        self.assertEqual(rep['party_support_scope'], 'turnout weighting groups only')
        self.assertEqual(rep['forecast_status'], 'not_estimable')

    def test_party_support_changes_do_not_change_current_frames(self):
        import tempfile, shutil
        a, _ = F.current_frames(self.cfg, ['A_support_check'])
        P = json.loads((ROOT / 'data/polls.json').read_text(encoding='utf-8'))
        Q = copy.deepcopy(P)
        for p in Q['polls']:
            if p['question_type'] == 'party_support':
                p['shares'] = {k: 0.99 for k in p['shares']}
        orig = F.load_json
        F.load_json = lambda path: Q if path == 'data/polls.json' else orig(path)
        try:
            b, _ = F.current_frames(self.cfg, ['A_support_check'])
        finally:
            F.load_json = orig
        self.assertEqual(a['logit'], b['logit'])

    def test_crossing_interpolation(self):
        self.assertAlmostEqual(F.crossing([0, 1], [150, 100], 125), 0.5)
        self.assertIsNone(F.crossing([0, 1], [150, 140], 125))


class PriorAndSeriesTests(unittest.TestCase):
    def test_prior_decays_to_zero_at_election_quarter(self):
        FP_main = FP.main
        out = ROOT / 'outputs' / 'fundamentals_prior.json'
        keep = out.read_bytes()
        try:
            FP_main(as_of_fieldwork='2028-04-01', election='2028-04-12')
            d = json.loads(out.read_text(encoding='utf-8'))
            self.assertAlmostEqual(d['prior_frame_logit_shift_mean'], 0.0)
        finally:
            out.write_bytes(keep)

    def test_series_crosscheck_flag_and_no_party_support(self):
        g = json.loads((ROOT / 'data/history_polls/gallup_series_v030.json').read_text(encoding='utf-8'))
        self.assertTrue(g['crosscheck_passed'])
        self.assertFalse(g['party_support_included'])
        self.assertEqual(len(g['quarterly_approval_tenure']['rows']), 8)


class ReleaseToolTests(unittest.TestCase):
    def test_validate_list_and_legacy_archive(self):
        r = subprocess.run([sys.executable, 'scripts/validate.py', '--list'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn('archived legacy scripts: 20', r.stdout)
        self.assertFalse(list((ROOT / 'scripts').glob('validate_release_*.py')))


if __name__ == '__main__':
    unittest.main()
