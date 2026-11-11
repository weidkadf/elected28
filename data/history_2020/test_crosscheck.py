"""Tests of exact extraction, full source coverage and parser fail-closed guards."""
import hashlib
import json
from pathlib import Path
import unittest
import zipfile
from crosscheck_official_tables import crosscheck, display_name, number, read_table

ROOT = Path(__file__).resolve().parent


class CrosscheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = crosscheck()
        with zipfile.ZipFile(ROOT / 'nec_2020_original_tables.zip') as z:
            cls.examples = {}
            for info in z.infolist():
                name = display_name(info)
                if name in ['지역구/1서울/개표상황(투표구별)_종로구.xlsx',
                            '지역구/2부산/개표상황(투표구별)_사상구.xlsx',
                            '비례대표/2부산/개표상황(투표구별)_사상구.xlsx']:
                    cls.examples[name] = z.read(info)

    def test_every_district_and_candidate_label_checked(self):
        self.assertEqual(self.report['status'], 'PASS')
        self.assertEqual(self.report['districts_passed'], 253)
        self.assertEqual(self.report['candidate_labels_checked'], 1101)
        self.assertEqual(self.report['official_workbooks'], 329)

    def test_proportional_and_byelection_tables_excluded(self):
        self.assertEqual(self.report['excluded_xlsx_by_category'], {'비례대표': 250, '재보궐': 56})

    def test_historical_validation_not_future_geography(self):
        self.assertTrue(self.report['historical_district_totals_verified'])
        self.assertFalse(self.report['model_eligible'])
        self.assertIn('2020_to_2024_boundary_crosswalk', self.report['remaining_gates'])

    def test_known_original_header_and_totals(self):
        data = self.examples['지역구/1서울/개표상황(투표구별)_종로구.xlsx']
        key, jurisdiction, votes, totals = read_table(data)
        self.assertEqual(key, ('서울특별시', '종로구'))
        self.assertEqual(jurisdiction, '종로구')
        self.assertEqual(votes[('더불어민주당', '이낙연')], 54902)
        self.assertEqual(totals['valid'], 94038)

    def test_alternate_official_title_supported(self):
        key, _, votes, _ = read_table(self.examples['지역구/2부산/개표상황(투표구별)_사상구.xlsx'])
        self.assertEqual(key, ('부산광역시', '사상구'))
        self.assertEqual(votes[('미래통합당', '장제원')], 66353)

    def test_proportional_table_cannot_pass_district_parser(self):
        with self.assertRaises(ValueError):
            read_table(self.examples['비례대표/2부산/개표상황(투표구별)_사상구.xlsx'])

    def test_unknown_nonnumeric_or_negative_votes_rejected(self):
        for value in ['', '사퇴', '-1', '1.5', '1,000']:
            with self.assertRaises(ValueError):
                number(value)

    def test_reconstruction_source_hash_still_matches(self):
        expected = '44bdb7be9caf743ea2a897ede8f9ccd4587bed89c5d03fe7b82dff5c1df40f04'
        self.assertEqual(hashlib.sha256((ROOT / 'nec_2020_raw.csv').read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
