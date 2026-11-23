import csv
import json
import sys
import unittest
from collections import Counter
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
        with (ROOT / 'data/district_panel.csv').open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 254)
        electors = sum(int(r['pres2025_electors']) for r in rows)
        self.assertLess(abs(electors - 44391871), 10)
        turnout = sum(int(r['pres2025_votes']) for r in rows) / electors
        self.assertAlmostEqual(turnout, 0.794, places=3)
        self.assertEqual(sum(r['gen2024_two_party_dem'] != '' for r in rows), 245)
        self.assertEqual(sum(r['gov2026_two_party_dem'] != '' for r in rows), 254)

    def test_unassigned_votes_small(self):
        rep = json.loads((ROOT / 'outputs/dong_panel_report.json').read_text(encoding='utf-8'))
        for el in rep['elections'].values():
            self.assertLess(el['unassigned_vote_share'], 0.005)
            self.assertEqual(el['county_level_votes_not_allocated'], 0)

    def test_incheon_reorganization_and_local_election_totals(self):
        dongs_by_predecessor = {
            '중구강화군옹진군': [('영종구', '운서1동'), ('영종구', '운서2동'), ('제물포구', '율목동')],
            '동구미추홀구갑': [('제물포구', '송현3동'), ('제물포구', '송림2동'), ('제물포구', '금창동')],
            '서구병': [('검단구', '아라1동'), ('검단구', '아라2동')],
        }
        expected = {dong: district for district, dongs in dongs_by_predecessor.items() for dong in dongs}
        with (ROOT / 'data/dong_panel.csv').open(encoding='utf-8') as f:
            dongs = list(csv.DictReader(f))
        with (ROOT / 'data/district_panel.csv').open(encoding='utf-8') as f:
            districts = list(csv.DictReader(f))
        report = json.loads((ROOT / 'outputs/dong_panel_report.json').read_text(encoding='utf-8'))
        for election in ('gov2026', 'mayor2026'):
            filename, vote_mode = P.ELECTIONS[election]
            totals, incheon = Counter(), Counter()
            with (P.RAW / filename).open(encoding='utf-8-sig') as f:
                for r in csv.DictReader(f):
                    label = r['후보자']
                    n = int(r['득표수'] or 0)
                    totals[label] += n
                    dong = (r['구시군명'], r['읍면동명'])
                    if r['시도명'] == '인천광역시' and r[vote_mode] and dong in expected:
                        incheon[dong, label] += n
            actual = {}
            for row in dongs:
                dong = (row['sigungu'], row['dong'])
                if row['election'] != election or row['sido'] != '인천광역시' or dong not in expected:
                    continue
                actual[dong] = row['district_2024']
                self.assertEqual(int(row['electors']), incheon[dong, '선거인수'])
                self.assertEqual(int(row['votes']), incheon[dong, '투표수'])
            self.assertEqual(actual, expected)
            self.assertEqual(report['elections'][election]['unassigned_vote_share'], 0.0)
            self.assertEqual(report['elections'][election]['map_status']['no_candidate_district'], 0)
            result = {'electors': totals['선거인수'], 'votes': totals['투표수']}
            for label, n in totals.items():
                if label not in P.META:
                    column = {P.DEM: 'dem', P.CON: 'con'}.get(P.party_of(label), 'third')
                    result[column] = result.get(column, 0) + n
            for column, total in result.items():
                self.assertEqual(sum(int(r[f'{election}_{column}']) for r in districts), total, (election, column))


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
