"""Check historical frame-only archive retention, not model eligibility."""
from datetime import date
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent


class HistoricalFrameArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((ROOT/'data/history_polls/gallup_394_frame_observations.json').read_text())
        cls.polls=cls.data['polls']

    def test_all_observations_are_frame_only_and_ineligible(self):
        self.assertEqual(len(self.polls),9)
        self.assertFalse(self.data['party_support_included'])
        for p in self.polls:
            self.assertEqual(p['question_type'],'government_frame')
            self.assertFalse(p['party_support_used'])
            self.assertFalse(p['model_input_eligible'])
            self.assertFalse(p['direct_vote_mapping_allowed'])

    def test_publication_precedes_2020_election_without_invented_time(self):
        for p in self.polls:
            self.assertLessEqual(date.fromisoformat(p['fieldwork_end']),date.fromisoformat(p['published_at']))
            self.assertLess(date.fromisoformat(p['published_at']),date(2020,4,15))
            self.assertEqual(p['published_at'],'2020-03-27')
            self.assertIsNone(p['publication_time'])

    def test_national_values_roles_sample_and_suppression(self):
        p=next(p for p in self.polls if p['scope']=='national')
        self.assertEqual(p['sample_size'],1001)
        self.assertEqual(p['weighted_sample_size'],1000)
        self.assertEqual(p['shares']['정부지원'],.46)
        self.assertEqual(p['shares']['정부견제'],.4)
        self.assertEqual(p['governing_party'],'더불어민주당')
        self.assertEqual(p['main_opposition_party'],'미래통합당')
        self.assertEqual(sum(bool(p['suppressed']) for p in self.polls),2)

    def test_original_pdf_hash_and_current_inputs_remain_separate(self):
        raw=(ROOT/self.data['source_file']).read_bytes()
        self.assertTrue(raw.startswith(b'%PDF-'))
        self.assertEqual(hashlib.sha256(raw).hexdigest(),self.data['source_sha256'])
        current=json.loads((ROOT/'data/polls.json').read_text())
        ids={p['poll_id'] for p in self.polls}
        self.assertFalse(ids & {p.get('poll_id') for p in current['polls']})


if __name__=='__main__':unittest.main()
