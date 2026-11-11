"""Explicit cross-election role/method profiles are audit metadata, not fitting."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.validate_historical_frames import archive_inventory

ROOT = Path(__file__).resolve().parent


class HistoricalRoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.docs = []
        for number in (394, 578):
            doc = json.loads((ROOT / f'data/history_polls/gallup_{number}_frame_observations.json').read_text())
            self.docs.append(doc)
            target = self.root / doc['source_file']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / doc['source_file'], target)

    def inventory(self, cutoff='2026-10-17'):
        paths = []
        for i, doc in enumerate(self.docs):
            path = self.root / f'wave_{i}.json'
            path.write_text(json.dumps(doc, ensure_ascii=False))
            paths.append(path)
        return archive_inventory(self.root, paths, cutoff)

    def test_original_role_reversal_recorded_without_successor_mapping(self):
        result = self.inventory()
        waves = {w['target_election_date']: w for w in result['waves']}
        old, new = waves['2020-04-15'], waves['2024-04-10']
        self.assertEqual((old['governing_party'], old['main_opposition_party'],
                          old['democratic_coordinate_component']),
                         ('더불어민주당', '미래통합당', '정부지원'))
        self.assertEqual((new['governing_party'], new['main_opposition_party'],
                          new['democratic_coordinate_component']),
                         ('국민의힘', '더불어민주당', '정부견제'))
        self.assertNotEqual(old['role_profile_id'], new['role_profile_id'])
        self.assertFalse(result['party_successor_mapping_created'])

    def test_coverage_is_separate_by_target_election(self):
        result = self.inventory('2024-03-15')
        self.assertEqual(result['target_election_coverage'], [
            {'target_election_date': '2020-04-15', 'wave_count': 1,
             'observation_count': 9, 'available_observations': 9},
            {'target_election_date': '2024-04-10', 'wave_count': 1,
             'observation_count': 9, 'available_observations': 0}])

    def test_2024_same_day_excluded_next_day_available(self):
        self.docs = [self.docs[1]]
        result = self.inventory('2024-03-15')
        self.assertEqual(result['available_observations'], 0)
        self.assertEqual({r['cutoff_exclusion_reason'] for r in result['observations']},
                         {'unknown_release_time_on_cutoff_day'})
        self.assertEqual(self.inventory('2024-03-16')['available_observations'], 9)

    def test_2024_future_publication_excluded(self):
        self.docs = [self.docs[1]]
        result = self.inventory('2024-03-14')
        self.assertEqual(result['available_observations'], 0)
        self.assertEqual({r['cutoff_exclusion_reason'] for r in result['observations']},
                         {'published_after_cutoff'})

    def test_2024_government_opposition_swapped_rejected(self):
        p = self.docs[1]['polls'][0]
        p['governing_party'], p['main_opposition_party'] = p['main_opposition_party'], p['governing_party']
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.inventory()

    def test_2024_coordinate_must_be_check(self):
        self.docs[1]['polls'][0]['democratic_coordinate_component'] = '정부지원'
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.inventory()

    def test_2024_three_option_question_rejected(self):
        self.docs[1]['polls'][0]['answer_options_exact'].append('제3지대 후보가 많이 당선돼야 한다')
        with self.assertRaisesRegex(ValueError, 'question wording'):
            self.inventory()

    def test_2024_earlier_three_option_period_not_implicitly_approved(self):
        self.docs[1]['polls'][0]['fieldwork_start'] = '2024-03-05'
        with self.assertRaisesRegex(ValueError, 'role window'):
            self.inventory()

    def test_2024_april_outside_reviewed_window_rejected(self):
        p = self.docs[1]['polls'][0]
        p.update(fieldwork_start='2024-04-01', fieldwork_end='2024-04-02', published_at='2024-04-03')
        with self.assertRaisesRegex(ValueError, 'role window'):
            self.inventory()

    def test_unknown_election_not_automatically_mapped(self):
        self.docs[1]['polls'][0]['target_election_date'] = '2028-04-12'
        with self.assertRaisesRegex(ValueError, 'profile not reviewed'):
            self.inventory()

    def test_method_change_cannot_be_silently_pooled(self):
        for field in ('sampling', 'mode', 'population'):
            with self.subTest(field=field):
                original = self.docs[1]['polls'][0][field]
                self.docs[1]['polls'][0][field] = self.docs[0]['polls'][0][field]
                with self.assertRaisesRegex(ValueError, 'method profile'):
                    self.inventory()
                self.docs[1]['polls'][0][field] = original

    def test_2020_method_change_rejected(self):
        self.docs[0]['polls'][0]['sampling'] = self.docs[1]['polls'][0]['sampling']
        with self.assertRaisesRegex(ValueError, 'method profile'):
            self.inventory()

    def test_different_methods_remain_unapproved_for_pooling(self):
        result = self.inventory()
        self.assertEqual(len({w['sampling'] for w in result['waves']}), 2)
        for w in result['waves']:
            self.assertFalse(w['method_comparability_approved'])
        for flag in ('cross_election_pooling_approved', 'training_approved', 'current_model_linked',
                     'geography_approved', 'wave_pooling_or_weights_created'):
            self.assertFalse(result[flag])

    def test_party_support_mutation_and_deletion_full_output_invariance(self):
        expected = self.inventory()
        saved = copy.deepcopy(self.docs)
        for doc in self.docs:
            doc['polls'].append({'question_type': 'party_support', 'shares': {'가상정당': 1e200},
                                 'target_election_date': 'not-a-date', 'governing_party': None})
        self.assertEqual(expected, self.inventory())
        for doc in self.docs:
            doc['polls'][-1] = {'question_type': 'party_support', 'shares': None}
        self.assertEqual(expected, self.inventory())
        self.docs = saved
        self.assertEqual(expected, self.inventory())

    def test_no_direct_opposition_judgment_or_vote_mapping(self):
        for field in ('opposition_judgment_directly_measured', 'direct_vote_mapping_allowed'):
            with self.subTest(field=field):
                self.docs[1]['polls'][0][field] = True
                with self.assertRaises(ValueError):
                    self.inventory()
                self.docs[1]['polls'][0][field] = False

    def test_every_observation_exposes_same_reviewed_role_as_its_wave(self):
        result = self.inventory()
        waves = {w['target_election_date']: w for w in result['waves']}
        for row in result['observations']:
            wave = waves[row['target_election_date']]
            for field in ('role_profile_id', 'governing_party', 'main_opposition_party',
                          'democratic_coordinate_component'):
                self.assertEqual(row[field], wave[field])


if __name__ == '__main__':
    unittest.main()
