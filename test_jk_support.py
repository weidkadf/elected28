"""조국혁신당 PR split and 개혁신당 PR share sensitivity: NESDC party-support table, jk_support.json, seats_300.json pr_sensitivity."""
import csv, json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent
KEYS = ('total_300', 'pr', 'p10_p50_p90', 'p_majority_151')


class JKSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.j = json.loads((ROOT / 'outputs/jk_support.json').read_text(encoding='utf-8'))
        cls.s = json.loads((ROOT / 'outputs/seats_300.json').read_text(encoding='utf-8'))
        with (ROOT / 'data/nesdc/party_support_national.csv').open(encoding='utf-8') as f:
            cls.rows = list(csv.DictReader(f))

    def test_table_is_unique_and_dated(self):
        self.assertEqual(len(self.rows), self.j['source']['n_rows'])
        self.assertEqual(len({r['reg_no'] for r in self.rows}), len(self.rows))
        for r in self.rows:
            self.assertLessEqual(r['fieldwork_start'], r['fieldwork_end'])
            self.assertIn(r['mode'], ('ARS', 'CATI', 'mixed'))

    def test_excluded_pollster_not_pooled(self):
        lo, hi = self.j['current']['window']
        n = sum(1 for r in self.rows if lo < r['fieldwork_end'] <= hi and r['조국혁신당'] and '여론조사꽃' not in r['pollster'])
        self.assertEqual(n, self.j['current']['all']['n_polls'])

    def test_calibration_and_scenarios_ordered(self):
        self.assertGreaterEqual(self.j['pre2024']['all']['n_polls'], 10)
        self.assertGreater(self.j['list_vote_uplift_logit'], 0)        # 2024 polls understated the list vote
        sc = self.j['scenarios']
        self.assertAlmostEqual(sc['fixed_2024']['ratio'], 24.25 / (26.69 + 24.25), places=4)
        # direct < swing follows from the positive list-vote uplift; the order against 2024 depends on new polls, so not asserted
        self.assertTrue(0 < sc['poll_direct']['ratio'] < sc['poll_swing']['ratio'] < 1)

    def test_main_output_is_the_fixed_scenario(self):
        g = self.s['pr_sensitivity']['grid']
        self.assertEqual(len(g), 9)
        self.assertEqual(g['fixed_2024|fixed_2024']['by_alpha'], [{k: r[k] for k in KEYS} for r in self.s['by_alpha']['rows']])

    def test_split_moves_only_within_the_bloc(self):
        g = self.s['pr_sensitivity']['grid']; base = g['fixed_2024|fixed_2024']['posterior_all_three']
        for k in ('poll_swing', 'poll_direct'):
            r = g[f'{k}|fixed_2024']['posterior_all_three']
            # 조국혁신당 can fall under the 3% threshold in low-Dem draws, which moves a fraction of a seat to the others
            self.assertLessEqual(abs(r['pr']['국민의힘'] - base['pr']['국민의힘']), 0.2)
            lower = self.s['pr_sensitivity']['jk'][k]['ratio'] < self.s['pr_sensitivity']['jk']['fixed_2024']['ratio']
            self.assertEqual(r['pr']['조국혁신당'] <= base['pr']['조국혁신당'], lower)
            self.assertLessEqual(abs(r['total_300']['민주+조국혁신당'] - base['total_300']['민주+조국혁신당']), 1.0)

    def test_reform_share_and_threshold(self):
        rf = self.j['reform']
        self.assertGreaterEqual(rf['pre2024']['all']['n_polls'], 10)
        self.assertEqual(rf['current']['all']['n_polls'], self.j['current']['all']['n_polls'])
        sc = rf['scenarios']; self.assertEqual(sc['fixed_2024']['share_pct'], 3.61)
        g = self.s['pr_sensitivity']['grid']
        for kj in ('fixed_2024', 'poll_swing', 'poll_direct'):
            for kr, v in sc.items():
                pr = g[f'{kj}|{kr}']['posterior_all_three']['pr']
                if v['share_pct'] < 3.0: self.assertEqual(pr['개혁신당'], 0.0)
                else: self.assertGreater(pr['개혁신당'], 0.0)
                self.assertAlmostEqual(sum(pr.values()), 46.0, delta=0.2)


if __name__ == '__main__':
    unittest.main()
