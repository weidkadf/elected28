import copy
import unittest
from scripts.build_backtest_readiness import ROOT, readiness_report, split_as_of
from scripts.validate_historical_frames import archive_inventory


class BacktestReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = archive_inventory(ROOT, (ROOT / 'data/history_polls').glob('*_frame_observations.json'), '2026-10-18')

    def split(self, cutoff='2024-03-16', inventory=None, baseline='2020-04-15', target='2024-04-10'):
        return split_as_of(self.inventory if inventory is None else inventory, baseline, target, cutoff)

    def test_separate_original_election_groups(self):
        result = self.split()
        self.assertEqual(result['baseline_frame_archive']['wave_count'], 3)
        self.assertEqual(result['target_frame_archive']['wave_count'], 1)
        self.assertEqual({r['democratic_coordinate_component'] for r in result['baseline_frame_archive']['observations']}, {'정부지원'})
        self.assertEqual({r['democratic_coordinate_component'] for r in result['target_frame_archive']['observations']}, {'정부견제'})

    def test_publication_day_not_available(self):
        self.assertEqual(self.split('2024-03-15')['target_frame_archive']['observation_count'], 0)
        self.assertEqual(self.split('2024-03-16')['target_frame_archive']['observation_count'], 9)

    def test_future_changes_do_not_change_selected_manifest(self):
        changed = copy.deepcopy(self.inventory)
        for row in changed['observations']:
            if row['target_election_date'] == '2024-04-10':
                row['sample_size'] = -999
                row['source_sha256'] = 'changed-future-source'
        self.assertEqual(self.split('2024-03-14'), self.split('2024-03-14', changed))

    def test_unrelated_election_not_pooled(self):
        changed = copy.deepcopy(self.inventory)
        changed['observations'].append({'target_election_date': '2028-04-12'})
        self.assertEqual(self.split(), self.split(inventory=changed))

    def test_non_frame_metadata_cannot_affect_selection(self):
        changed = copy.deepcopy(self.inventory)
        changed['party_support'] = {'malformed': [None, -999]}
        for row in changed['observations']:
            row['party_support'] = {'arbitrary': 10000}
        self.assertEqual(self.split(), self.split(inventory=changed))

    def test_order_is_deterministic(self):
        changed = copy.deepcopy(self.inventory)
        changed['observations'].reverse()
        self.assertEqual(self.split(), self.split(inventory=changed))

    def test_same_election_baseline_rejected(self):
        with self.assertRaises(ValueError):
            self.split(baseline='2024-04-10')

    def test_invalid_cutoffs_rejected(self):
        for cutoff in ('2020-04-15', '2019-01-01', '2024-04-10', '2024-04-11'):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                self.split(cutoff)

    def test_incomplete_selected_wave_rejected(self):
        changed = copy.deepcopy(self.inventory)
        changed['observations'] = [r for r in changed['observations']
                                   if r['poll_id'] != 'gallup_578_frame_national']
        with self.assertRaises(ValueError):
            self.split(inventory=changed)

    def test_unvalidated_or_party_used_archive_rejected(self):
        for field, value in [('status', 'FAIL'), ('party_support_used', True)]:
            changed = copy.deepcopy(self.inventory)
            changed[field] = value
            with self.assertRaises(ValueError):
                self.split(inventory=changed)

    def test_duplicate_selected_id_rejected(self):
        changed = copy.deepcopy(self.inventory)
        changed['observations'].append(copy.deepcopy(changed['observations'][0]))
        with self.assertRaises(ValueError):
            self.split(inventory=changed)

    def test_actual_five_folds_remain_blocked_without_metrics(self):
        report = readiness_report()
        self.assertEqual(report['fold_count'], 5)
        self.assertEqual(report['executable_fold_count'], 0)
        self.assertIsNone(report['performance_metrics'])
        self.assertFalse(report['target_election_result_used_as_input'])
        for fold in report['folds']:
            self.assertEqual(fold['status'], 'BLOCKED')
            self.assertFalse(fold['backtest_executed'])
            self.assertIn('geographic_crosswalk_not_approved', fold['blockers'])
        self.assertEqual([f['selected_archive_manifest']['target_frame_archive']['wave_count'] for f in report['folds']], [0, 0, 1, 2, 3])


if __name__ == '__main__':
    unittest.main()
