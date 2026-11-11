"""v0.5.1 tests: alpha identification (micro, regional, prior) and the seat distribution."""
import json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent


class AlphaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = json.loads((ROOT / 'outputs/alpha_identification.json').read_text(encoding='utf-8'))

    def test_micro_is_tight_and_below_one(self):
        m = self.d['micro']
        self.assertGreaterEqual(m['n_polls'], 60)
        self.assertGreaterEqual(m['n_pollsters'], 10)
        self.assertTrue(0.6 < m['mean_of_pollster_means'] < 0.95)
        self.assertLess(m['sd_between_pollsters'], 0.15)
        for p in m['polls']:
            self.assertGreater(p['v_dem_side'], p['v_other_side'])

    def test_regional_windows_cover_all_scopes(self):
        for w in self.d['regional']['windows'].values():
            self.assertEqual(len(w['dev']), 8)
            self.assertGreaterEqual(w['n_polls'], 10)
        for p in self.d['regional']['pairs'].values():
            self.assertGreater(p['n_districts'], 200)
            self.assertGreater(p['x_reliability'], 0.5)

    def test_posteriors_and_seats(self):
        post = self.d['combined']['posteriors']
        for k in ('all_three', 'micro_plus_region', 'all_three_excluding_presidential_pair'):
            lo, hi = post[k]['ci95']
            self.assertTrue(lo < post[k]['mean'] < hi)
            self.assertLess(hi - lo, 1.0)          # narrower than the unidentified (-3, 3)
        s = self.d['seat_distribution']['all_three']
        self.assertAlmostEqual(s['dem_mean'] + s['con_mean'], 254, delta=3)
        self.assertTrue(0 <= s['p_dem_district_majority'] <= 1)

    def test_routes_disagree_is_recorded(self):
        r = self.d['regional']['joint_free_intercepts']
        self.assertLess(r['ci95'][1], self.d['micro']['mean_of_pollster_means'])   # documented tension, not hidden


if __name__ == '__main__':
    unittest.main()
