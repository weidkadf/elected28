"""Primary weekly table regression, not approval to pool or fit election votes."""
import copy
import hashlib
import json
import unittest
from scripts.build_backtest_readiness import ROOT, split_as_of
from scripts.validate_historical_frames import archive_inventory


class Historical580Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads((ROOT / 'data/history_polls/gallup_580_frame_observations.json').read_text())
        cls.rows = {p['scope']: p for p in cls.doc['polls']}
        cls.inventory = archive_inventory(ROOT, (ROOT / 'data/history_polls').glob('*_frame_observations.json'), '2026-10-18')

    def test_primary_pdf_page14_exact_weekly_table(self):
        expected = {'national': (1001,1001,40,49,11), '서울': (180,187,44,46,9),
                    '인천/경기': (325,320,36,54,10), '강원': (28,30,None,None,None),
                    '대전/세종/충청': (100,107,49,34,17), '광주/전라': (104,97,6,78,15),
                    '대구/경북': (98,97,63,29,9), '부산/울산/경남': (150,150,41,52,8),
                    '제주': (16,13,None,None,None)}
        self.assertEqual(set(self.rows), set(expected))
        for scope, (n,wn,s,c,u) in expected.items():
            row = self.rows[scope]
            self.assertEqual((row['sample_size'],row['weighted_sample_size'],row['pdf_page']), (n,wn,14))
            self.assertEqual(row['shares'], {} if s is None else {'정부지원':s/100,'정부견제':c/100,'모름/응답거절':u/100})

    def test_exact_period_publication_and_method(self):
        for row in self.rows.values():
            self.assertEqual((row['fieldwork_start'],row['fieldwork_end'],row['published_at']),
                             ('2024-03-26','2024-03-28','2024-03-29'))
            self.assertEqual(row['response_rate'], .154)
            self.assertEqual(row['democratic_coordinate_component'], '정부견제')
            self.assertFalse(row['opposition_judgment_directly_measured'])

    def test_new_sources_match_retained_hashes(self):
        for pathkey,hashkey in [('source_file','source_sha256'),('source_html_file','source_html_sha256')]:
            self.assertEqual(hashlib.sha256((ROOT/self.doc[pathkey]).read_bytes()).hexdigest(),self.doc[hashkey])

    def test_archive_has_six_waves_not_54_independent_surveys(self):
        self.assertEqual((self.inventory['wave_count'],self.inventory['observation_count']), (6,54))
        self.assertFalse(self.inventory['national_and_regions_independent'])
        self.assertFalse(self.inventory['training_approved'])
        self.assertFalse(self.inventory['wave_pooling_or_weights_created'])

    def test_monthly_not_added_or_current_input_linked(self):
        self.assertEqual(len(self.doc['polls']),9)
        self.assertEqual({p['overlap_group'] for p in self.doc['polls']}, {'gallup_20240326_28'})
        self.assertFalse(self.inventory['current_model_linked'])
        self.assertTrue(all(p['model_input_eligible'] is False for p in self.doc['polls']))

    def test_580_publication_day_excluded_next_day_available(self):
        counts = []
        for cutoff in ('2024-03-29','2024-03-30'):
            selected = split_as_of(self.inventory,'2020-04-15','2024-04-10',cutoff)
            counts.append(selected['target_frame_archive']['wave_count'])
        self.assertEqual(counts,[2,3])

    def test_future_580_metadata_cannot_change_earlier_manifest(self):
        changed = copy.deepcopy(self.inventory)
        for row in changed['observations']:
            if row['poll_id'].startswith('gallup_580_'):
                row['sample_size'] = -999
                row['source_sha256'] = 'future-mutation'
        args = ('2020-04-15','2024-04-10','2024-03-29')
        self.assertEqual(split_as_of(self.inventory,*args),split_as_of(changed,*args))

    def test_580_has_only_frame_question_and_missing_not_zero(self):
        self.assertEqual({p['question_type'] for p in self.doc['polls']},{'government_frame'})
        self.assertEqual({s for s,r in self.rows.items() if r['suppressed']},{'강원','제주'})
        self.assertTrue(all(p['party_support_used'] is False for p in self.doc['polls']))


if __name__ == '__main__':
    unittest.main()
