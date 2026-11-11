"""Historical accounting partition tests; no electoral transfer is authorized."""
from pathlib import Path
import unittest
from scripts.build_2020_ward_inventory import build_inventory,signed_count


class WardInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.units,cls.districts,cls.report=build_inventory()

    def test_complete_original_workbook_and_district_coverage(self):
        self.assertEqual(self.report['official_workbooks_checked'],329)
        self.assertEqual(len(self.districts),253)

    def test_every_selected_row_has_unique_source_coordinate(self):
        keys={(u['source_member'],u['source_row_1based']) for u in self.units}
        self.assertEqual(len(keys),len(self.units))
        self.assertTrue(all(u['source_row_1based']>7 for u in self.units))

    def test_ward_and_special_row_counts(self):
        self.assertEqual(self.report['named_ward_rows'],3485)
        self.assertEqual(self.report['unlocated_category_rows'],1645)
        self.assertEqual(len(self.units),5130)

    def test_national_valid_vote_partition(self):
        r=self.report
        self.assertEqual(r['national_valid_votes'],28741408)
        self.assertEqual(r['named_ward_valid_votes'],25941047)
        self.assertEqual(r['unlocated_valid_votes'],2800361)
        self.assertEqual(r['named_ward_valid_votes']+r['unlocated_valid_votes'],r['national_valid_votes'])

    def test_candidate_partitions_reconcile_in_every_district(self):
        for d in self.districts:
            self.assertEqual(d['named_ward_valid_votes']+d['unlocated_valid_votes'],d['valid_votes'])
            for c in d['candidate_partition']:
                self.assertEqual(c['named_ward']+c['unlocated'],c['total'])

    def test_every_district_keeps_special_votes_unallocated(self):
        self.assertEqual(self.report['districts_with_positive_unlocated_votes'],253)
        self.assertTrue(all(not d['crosswalk_eligible'] for d in self.districts))
        self.assertTrue(all(u['target_2024_district'] is None and not u['crosswalk_eligible'] for u in self.units))
        self.assertFalse(self.report['allocation_weights_created'])

    def test_gildong_original_subtotal(self):
        u=next(u for u in self.units if u['province']=='서울특별시' and u['district']=='강동구갑' and u['unit_label']=='길동')
        self.assertEqual(u['totals']['valid'],22697)
        self.assertEqual(u['source_row_1based'],77)

    def test_sinpyeong2_original_subtotal(self):
        u=next(u for u in self.units if u['province']=='부산광역시' and u['district']=='사하구을' and u['unit_label']=='신평제2동')
        self.assertEqual(u['totals']['valid'],8663)
        self.assertEqual(u['source_row_1based'],18)

    def test_special_categories_are_not_counted_as_wards(self):
        labels=set(self.report['unlocated_category_valid_votes'])
        self.assertEqual(labels,{'거소·선상투표','관외사전투표','국외부재자투표','국외부재자투표(공관)','잘못 투입·구분된 투표지'})
        self.assertEqual(sum(self.report['unlocated_category_valid_votes'].values()),2800361)

    def test_signed_correction_abstentions_preserved(self):
        self.assertEqual(signed_count('-3',True),-3)
        with self.assertRaises(ValueError):signed_count('-3')
        self.assertTrue(any(u['totals']['abstentions']<0 for u in self.units))


if __name__=='__main__':unittest.main()
