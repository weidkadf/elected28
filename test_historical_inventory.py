"""Regression gates for historical archives, not forecast calibration."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.validate_historical_frames import archive_inventory

ROOT = Path(__file__).resolve().parent


class HistoricalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'wave_frame_observations.json'
        self.doc = json.loads((ROOT / 'data/history_polls/gallup_394_frame_observations.json').read_text())
        target = self.root / self.doc['source_file']
        target.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / self.doc['source_file'], target)

    def run_archive(self, cutoff='2026-10-17', paths=None):
        self.path.write_text(json.dumps(self.doc, ensure_ascii=False))
        return archive_inventory(self.root, paths or [self.path], cutoff)

    def test_complete_inventory_not_training_approval(self):
        result = self.run_archive()
        self.assertEqual((result['wave_count'], result['observation_count']), (1, 9))
        self.assertEqual(result['available_observations'], 9)
        for field in ['training_approved', 'current_model_linked', 'geography_approved',
                      'party_successor_mapping_created', 'national_and_regions_independent',
                      'wave_pooling_or_weights_created']:
            self.assertFalse(result[field])

    def test_party_support_deleted_or_malformed_has_no_effect(self):
        expected = self.run_archive()
        self.doc['polls'].append({'question_type': 'party_support', 'published_at': 'not-a-date',
                                  'sample_size': -1, 'shares': {'invented': 1e99}})
        self.assertEqual(expected, self.run_archive())
        self.doc['polls'][-1] = {'question_type': 'party_support'}
        self.assertEqual(expected, self.run_archive())

    def test_publication_day_excluded_and_next_day_available(self):
        result = self.run_archive('2020-03-27')
        self.assertEqual(result['available_observations'], 0)
        self.assertEqual({r['cutoff_exclusion_reason'] for r in result['observations']},
                         {'unknown_release_time_on_cutoff_day'})
        self.assertEqual(self.run_archive('2020-03-28')['available_observations'], 9)

    def test_future_publication_excluded(self):
        result = self.run_archive('2020-03-26')
        self.assertEqual({r['cutoff_exclusion_reason'] for r in result['observations']},
                         {'published_after_cutoff'})

    def test_fieldwork_after_publication_rejected(self):
        self.doc['polls'][0]['published_at'] = '2020-03-25'
        with self.assertRaisesRegex(ValueError, 'chronology'):
            self.run_archive()

    def test_post_election_publication_rejected(self):
        self.doc['polls'][0]['published_at'] = '2020-04-15'
        with self.assertRaisesRegex(ValueError, 'chronology'):
            self.run_archive()

    def test_original_party_not_relabelled_as_successor(self):
        self.doc['polls'][0]['main_opposition_party'] = '국민의힘'
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.run_archive()

    def test_wrong_role_direction_rejected(self):
        self.doc['polls'][0]['democratic_coordinate_component'] = '정부견제'
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.run_archive()

    def test_source_tamper_rejected(self):
        with (self.root / self.doc['source_file']).open('ab') as stream:
            stream.write(b'tamper')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.run_archive()

    def test_suppressed_region_not_filled_with_zeros(self):
        p = next(p for p in self.doc['polls'] if p['suppressed'])
        p['shares'] = {'정부지원': 0, '정부견제': 0, '모름/응답거절': 0}
        with self.assertRaisesRegex(ValueError, 'remain missing'):
            self.run_archive()

    def test_duplicate_wave_scope_across_files_rejected(self):
        other = self.root / 'copy_frame_observations.json'
        altered = copy.deepcopy(self.doc)
        for p in altered['polls']:
            p['poll_id'] += '_copy'
        other.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'duplicate wave/scope'):
            self.run_archive(paths=[self.path, other])

    def test_incomplete_scope_partition_rejected(self):
        self.doc['polls'].pop()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.run_archive()

    def test_raw_sample_partition_rejected(self):
        self.doc['polls'][1]['sample_size'] += 1
        with self.assertRaisesRegex(ValueError, 'raw sample mismatch'):
            self.run_archive()

    def test_rounding_preserved_but_invalid_shares_rejected(self):
        self.assertEqual(self.run_archive()['status'], 'PASS')  # 99/101% regional rows are valid.
        self.doc['polls'][0]['shares']['정부지원'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'invalid frame share'):
            self.run_archive()

    def test_direct_opposition_judgment_mislabel_rejected(self):
        self.doc['polls'][0]['opposition_judgment_directly_measured'] = True
        with self.assertRaisesRegex(ValueError, 'direct opposition'):
            self.run_archive()

    def test_unreviewed_question_not_silently_pooled(self):
        self.doc['polls'][0]['answer_options_exact'][0] = '야당을 심판해야 한다'
        with self.assertRaisesRegex(ValueError, 'question wording'):
            self.run_archive()

    def test_empty_archive_not_success(self):
        with self.assertRaisesRegex(ValueError, 'no archive files'):
            archive_inventory(self.root, [], '2026-10-17')

    def test_unreviewed_pollster_rejected(self):
        self.doc['polls'][1]['pollster'] = '다른 조사기관'
        with self.assertRaisesRegex(ValueError, 'unreviewed pollster'):
            self.run_archive()


if __name__ == '__main__':
    unittest.main()
