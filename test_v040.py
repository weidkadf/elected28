"""v0.4.0 tests: dong panel mapping and its three uses."""
import csv
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
import build_dong_panel as P  # noqa: E402


class MappingTests(unittest.TestCase):
    def test_name_normalisation_and_suboffice_labels(self):
        self.assertEqual(P.norm_dong('둔촌제1동'), '둔촌1동')
        self.assertEqual(P.city_of('화성시을'), '화성시')
        self.assertEqual(P.city_of('수원시장안구'), '수원시')
        self.assertEqual(P.city_of('종로구'), '종로구')
        self.assertEqual(P.norm_sido('전남광주통합특별시', '광산구'), '광주광역시')
        self.assertEqual(P.norm_sido('전남광주통합특별시', '순천시'), '전라남도')

    def test_panel_totals_match_official(self):
        rows = list(csv.DictReader(open(ROOT / 'data/district_panel.csv', encoding='utf-8')))
        self.assertEqual(len(rows), 254)
        electors = sum(int(r['pres2025_electors']) for r in rows)
        self.assertLess(abs(electors - 44391871), 10)          # official 21st presidential electorate
        turnout = sum(int(r['pres2025_votes']) for r in rows) / electors
        self.assertAlmostEqual(turnout, 0.794, places=3)
        self.assertEqual(sum(r['gen2024_two_party_dem'] != '' for r in rows), 245)
        self.assertEqual(sum(r['gov2026_two_party_dem'] != '' for r in rows), 254)

    def test_unassigned_votes_small(self):
        rep = json.loads((ROOT / 'outputs/dong_panel_report.json').read_text(encoding='utf-8'))
        for el in rep['elections'].values():
            self.assertLess(el['unassigned_vote_share'], 0.005)
            self.assertEqual(el['county_level_votes_not_allocated'], 0)


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = json.loads((ROOT / 'outputs/dong_panel_analysis.json').read_text(encoding='utf-8'))

    def test_second_pair_does_not_identify_alpha_with_free_intercept(self):
        ci = self.a['alpha']['pair_2024_to_2026_governor']['fit_free_intercept']['alpha_ci95']
        self.assertLess(ci[0], 0)
        self.assertGreater(ci[1] - ci[0], 1.0)

    def test_baseline_2026_thresholds_ordered(self):
        t = self.a['baseline_2026']['majority_thresholds']['dem_loses_majority_alpha_bounds']
        self.assertLess(t['pending_9_all_non_dem'], t['pending_9_all_dem'])
        self.assertGreater(self.a['baseline_2026']['dem_seats_at_alpha0_no_noise'], 128)

    def test_turnout_levels(self):
        n = self.a['turnout_actual']['national']
        self.assertGreater(n['pres2025'], n['gen2024'])
        self.assertGreater(n['gen2024'], n['gov2026'])


if __name__ == '__main__':
    unittest.main()
