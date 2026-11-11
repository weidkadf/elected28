"""Statutory row inventory tests; none authorizes geographic vote transfer."""
import csv
import hashlib
import json
from pathlib import Path
import unittest

from scripts.build_boundary_inventory import build_inventory, compact

ROOT = Path(__file__).resolve().parent


class BoundaryInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.review, cls.summary = build_inventory()
        cls.by_key = {year: {(r['province'], r['district_name']): r for r in rows}
                      for year, rows in cls.rows.items()}

    def test_complete_statutory_row_counts(self):
        self.assertEqual({y:len(rows) for y,rows in self.rows.items()}, {2020:253,2024:254})
        self.assertTrue(self.summary['province_counts_match_source_headings'])

    def test_all_model_district_ids_join_exactly(self):
        with (ROOT/'data/districts_2024.csv').open(encoding='utf-8-sig', newline='') as f:
            ids = {r['district_id'] for r in csv.DictReader(f)}
        self.assertEqual({r['district_id'] for r in self.review}, ids)
        self.assertEqual(len(self.review), 254)

    def test_no_duplicate_statutory_keys(self):
        for year, rows in self.rows.items():
            self.assertEqual(len(self.by_key[year]), len(rows))

    def test_text_comparison_counts_are_a_partition_not_geographic_claim(self):
        counts = self.summary['comparison_status_counts']
        self.assertEqual(sum(counts.values()), 254)
        self.assertEqual(counts['same_name_same_statutory_text_geometry_unverified'], 171)
        self.assertEqual(counts['same_name_statutory_text_diff_review_required'], 61)
        self.assertEqual(counts['no_same_name_predecessor_review_required'], 22)

    def test_all_crosswalks_and_transfer_weights_remain_unavailable(self):
        self.assertEqual(self.summary['crosswalk_eligible_districts'], 0)
        self.assertTrue(all(not r['crosswalk_eligible'] and r['vote_transfer_weight'] is None for r in self.review))

    def test_gildong_moves_across_same_named_districts(self):
        a = self.by_key[2020][('서울특별시','강동구갑')]['statutory_area_compact'].split(',')
        b = self.by_key[2024][('서울특별시','강동구을')]['statutory_area_compact'].split(',')
        self.assertIn('길동', a)
        self.assertIn('길동', b)
        self.assertNotIn('길동', self.by_key[2024][('서울특별시','강동구갑')]['statutory_area_compact'].split(','))

    def test_sinpyeong2_moves_across_same_named_districts(self):
        self.assertIn('신평제2동', self.by_key[2020][('부산광역시','사하구을')]['statutory_area_compact'].split(','))
        self.assertIn('신평제2동', self.by_key[2024][('부산광역시','사하구갑')]['statutory_area_compact'].split(','))

    def test_nowon_three_to_two_districts(self):
        names = lambda year: {name for province,name in self.by_key[year] if province=='서울특별시' and name.startswith('노원구')}
        self.assertEqual(names(2020), {'노원구갑','노원구을','노원구병'})
        self.assertEqual(names(2024), {'노원구갑','노원구을'})

    def test_only_typographic_normalization(self):
        self.assertEqual(compact('금호2·3가동,\n 옥수동'), compact('금호2․3가동, 옥수동'))
        self.assertNotEqual(compact('상일동'), compact('상일제1동, 상일제2동'))

    def test_pdf_provenance_and_hashes(self):
        sources = json.loads((ROOT/'data/boundary_research/source_manifest.json').read_text())
        for source in sources:
            self.assertEqual(hashlib.sha256((ROOT/source['local_pdf']).read_bytes()).hexdigest(), source['sha256'])
        for rows in self.rows.values():
            self.assertTrue(all(r['pdf_page_1based']>=1 and r['table_row_1based']>=1 and r['source_url'] for r in rows))


if __name__ == '__main__':
    unittest.main()
