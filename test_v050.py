import copy, csv, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import forecast_v030 as F  # noqa: E402
import forecast_v050 as V  # noqa: E402


class RatingsTests(unittest.TestCase):
    def test_index_and_exclusion(self):
        with (ROOT / 'data/nesdc/nesdc_polls_index.csv').open(encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 964)
        self.assertFalse(any('꽃' in r['조사기관'] for r in rows))

    def test_mode_weights(self):
        r = json.loads((ROOT / 'outputs/pollster_ratings.json').read_text(encoding='utf-8'))
        m = r['mode_summary']
        for k in ('all_parsed', 'question_verified_only', 'final_week_from_0523'):
            self.assertLess(m[k]['ARS']['rmse_logit'], m[k]['CATI']['rmse_logit'])
        self.assertEqual(r['quality_weights_for_model']['ARS_RDD'], 1.0)
        self.assertLess(r['quality_weights_for_model']['CATI_live_interview'], 1.0)

    def test_frame_polls_match_nesdc_originals(self):
        d = json.loads((ROOT / 'data/frame_polls_v050.json').read_text(encoding='utf-8'))
        s = {p['poll_id']: p['shares'] for p in d['polls']}
        self.assertEqual((s['researchview_20261108_judgment_national']['support'], s['researchview_20261108_judgment_national']['check']), (0.34, 0.577))
        self.assertEqual(len(d['polls']), 6)


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = F.load_json('config/forecast_v050.json')
        cls.rep = V.build(cls.cfg, F.read_baseline(ROOT / 'data/baseline_2024.csv'), draws=400, seed=7)

    def test_all_254_simulated(self):
        d = self.rep['districts_main']
        self.assertEqual(len(d), 254)
        self.assertEqual(sum(x['formerly_pending'] for x in d), 9)
        p = self.rep['scenarios']['main_composite_254']['curve'][0]
        self.assertAlmostEqual(p['dem']['mean'] + p['con']['mean'] + p['other']['mean'], 254, places=6)

    def test_composite_is_centred_on_2024_environment(self):
        d = [x for x in self.rep['districts_main'] if x['dem_two_party_2024'] is not None]
        diff = sum(x['composite_baseline'] - x['dem_two_party_2024'] for x in d) / len(d)
        self.assertLess(abs(diff), 0.01)

    def test_dong_turnout_reweight_is_small(self):
        self.assertLess(self.rep['inputs']['dong_turnout_reweight_abs_change_pp']['max'], 1.0)

    def test_threshold_and_monotone(self):
        t = self.rep['headline']['majority_thresholds_main']['dem_loses_majority_alpha']
        v = list(t.values())
        self.assertEqual(v[0], v[1])
        self.assertTrue(0.1 < v[0] < 0.35)
        means = [p['dem']['mean'] for p in self.rep['scenarios']['main_composite_254']['curve']]
        self.assertTrue(all(a >= b - 0.5 for a, b in zip(means, means[1:])))
        self.assertEqual(self.rep['forecast_status'], 'not_estimable')

    def test_pres_lean_predicts_2026_better_than_2024(self):
        r = self.rep['validation_composite']['rmse_logit']
        self.assertLess(r['pres2025_only'], r['gen2024_only'])

    def test_turnout_switch_controls_each_scenario_and_seats(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['turnout_adjustment']['enabled_in_main'] = False
        off = V.build(cfg, F.read_baseline(ROOT / 'data/baseline_2024.csv'), draws=400, seed=7)
        for key, scenario in self.rep['scenarios'].items():
            on_shift = scenario['turnout_adjustment']
            self.assertNotEqual(on_shift['net_change_effect_logit'], 0.0, key)
            self.assertEqual(off['scenarios'][key]['turnout_adjustment'],
                             dict.fromkeys(on_shift, 0.0), key)
        on_main, off_main = (r['scenarios']['main_composite_254']['curve'] for r in (self.rep, off))
        self.assertEqual(on_main[0], off_main[0])
        self.assertNotEqual(on_main[10]['dem']['mean'], off_main[10]['dem']['mean'])

    def test_future_election_results_and_reweighting_are_excluded(self):
        cfg = copy.deepcopy(self.cfg)
        pres_info = cfg['composite_baseline']['election_results']['pres2025']
        cfg['as_of'] = pres_info['available_on']
        comp, nat = V.composite(cfg)
        self.assertNotIn('pres2025', nat)
        self.assertTrue(all(v['l25'] is None and v['l26'] is None for v in comp.values()))
        self.assertEqual(sum(v['p0'] is None for v in comp.values()), 9)
        cfg['as_of'] = cfg['composite_baseline']['election_results']['gov2026']['available_on']
        comp, nat = V.composite(cfg)
        self.assertIn('pres2025', nat)
        self.assertTrue(all(v['l26'] is None and v['p25_raw'] == v['p25_tw'] for v in comp.values()))
        self.assertEqual(V.turnout_reweighted_pres(cfg), {})
        cfg['as_of'] = self.cfg['as_of']
        self.assertTrue(V.turnout_reweighted_pres(cfg))


if __name__ == '__main__':
    unittest.main()
