"""Independent regression tests for availability and regional-frame identity.

Synthetic fixtures are separate from test_model.py so changing that module's
fixtures cannot silently weaken these guards. No party-support linkage allowed.
"""
import copy
import json
from pathlib import Path
import unittest

from model import DEM, CON, build_report, matched_frame_scenarios, read_baseline

ROOT = Path(__file__).resolve().parent


def inputs(as_of='2026-10-16'):
    old = {'poll_id': 'old', 'pollster': 'Synthetic', 'series_id': 'frame',
           'scope': 'national', 'question_type': 'government_frame',
           'fieldwork_end': '2024-03-28', 'published_at': '2024-03-29',
           'sample_size': 1000, 'source_url': 'https://example.test/old',
           'shares': {'정부지원': .4, '정부견제': .5, '유보': .1}}
    new = {**old, 'poll_id': 'new', 'fieldwork_end': '2024-04-08',
           'published_at': '2024-04-09', 'source_url': 'https://example.test/new'}
    data = {'as_of': as_of, 'polls': [old, new]}
    config = {'comparison_type': 'government_frame', 'baseline_poll_id': 'old',
              'current_poll_id': 'new', 'roles': {
                  'baseline': {'governing_party': CON, 'opposition_party': DEM},
                  'current': {'governing_party': DEM, 'opposition_party': CON}},
              'baseline_information': {'election_date': '2024-04-10',
                  'available_on': '2024-04-11', 'source_url': 'https://example.test/result',
                  'availability_basis': 'synthetic_fixture'},
              'regional_shrinkage_k': 400, 'transfer_coefficients': [1],
              'uncertainty_logit': {'national': .12, 'region': .1, 'district': .18}}
    districts = [{'district_id': 'test', 'region': '서울특별시',
                  'district_name': '가상지역구', 'errors': [], 'candidates': [
                      {'party': p, 'candidate': p+'가상', 'votes': v,
                       'valid_votes': 100, 'election_date': '2024-04-10',
                       'source_url': 'https://example.test/result'}
                      for p, v in [(DEM, 55), (CON, 45)]]}]
    return districts, data, config


def with_regions(baseline_scope='서울', current_scope='서울', suppressed=False):
    districts, data, config = inputs()
    for index, scope in [(0, baseline_scope), (1, current_scope)]:
        row = {**data['polls'][index], 'poll_id': ['old_region','new_region'][index],
               'scope': scope, 'sample_size': 200}
        if suppressed:
            row.update({'suppressed': True, 'shares': {}})
        data['polls'].append(row)
    config['regions'] = {'서울': {'baseline_poll_id': 'old_region',
                                'current_poll_id': 'new_region',
                                'baseline_regions': ['서울특별시']}}
    return districts, data, config


class SafetyGuardTests(unittest.TestCase):
    def assert_scope_blocked(self, data, config):
        scenarios, reasons = matched_frame_scenarios(data, config)
        self.assertEqual(scenarios, [])
        self.assertTrue(reasons)
        self.assertIn('scope', ' '.join(reasons).lower())

    def test_real_current_inputs_remain_accepted(self):
        districts = read_baseline(ROOT/'data/baseline_2024.csv')
        data = json.loads((ROOT/'data/polls.json').read_text())
        config = json.loads((ROOT/'config/frame_comparison.json').read_text())
        report = build_report(districts, data, config, draws=100)
        self.assertTrue(report['coverage']['complete'])
        self.assertEqual(len(report['baseline']), 254)
        self.assertEqual(report['frame_comparison_blockers'], [])
        self.assertTrue(report['scenarios'])
        for scenario in report['scenarios']:
            self.assertEqual(len(scenario['districts']), 254)
            self.assertTrue(all(scenario['checks'].values()))

    def test_future_baseline_result_is_rejected(self):
        districts, data, config = inputs('2024-04-09')
        with self.assertRaises(ValueError):
            build_report(districts, data, config, draws=100)

    def test_same_day_result_is_not_assumed_public(self):
        districts, data, config = inputs('2024-04-10')
        with self.assertRaises(ValueError):
            build_report(districts, data, config, draws=100)

    def test_missing_baseline_availability_metadata_is_rejected(self):
        districts, data, config = inputs()
        config.pop('baseline_information')
        with self.assertRaises(ValueError):
            build_report(districts, data, config, draws=100)

    def test_post_election_but_before_baseline_availability_is_rejected(self):
        districts, data, config = inputs('2024-04-11')
        config['baseline_information']['available_on'] = '2024-04-12'
        with self.assertRaises(ValueError):
            build_report(districts, data, config, draws=100)

    def test_exact_baseline_available_on_is_accepted(self):
        districts, data, config = inputs('2024-04-11')
        report = build_report(districts, data, config, draws=100)
        self.assertTrue(report['scenarios'])

    def test_missing_baseline_election_date_is_rejected(self):
        districts, data, config = inputs()
        for candidate in districts[0]['candidates']:
            candidate.pop('election_date')
        with self.assertRaises(ValueError):
            build_report(districts, data, config, draws=100)

    def test_malformed_baseline_election_date_is_rejected(self):
        districts, data, config = inputs()
        districts[0]['candidates'][1]['election_date'] = 'not-a-date'
        with self.assertRaises(ValueError):
            build_report(districts, data, config, draws=100)

    def test_wrong_baseline_region_is_rejected(self):
        _, data, config = with_regions(baseline_scope='광주/전라')
        self.assert_scope_blocked(data, config)

    def test_wrong_current_region_is_rejected(self):
        _, data, config = with_regions(current_scope='광주/전라')
        self.assert_scope_blocked(data, config)

    def test_national_anchor_cannot_be_reused_as_regional_poll(self):
        _, data, config = with_regions(current_scope='national')
        self.assert_scope_blocked(data, config)

    def test_suppression_does_not_bypass_region_identity(self):
        _, data, config = with_regions(current_scope='광주/전라', suppressed=True)
        self.assert_scope_blocked(data, config)

    def test_correct_scope_with_wrong_mapped_province_is_rejected(self):
        _, data, config = with_regions()
        config['regions']['서울']['baseline_regions'] = ['광주광역시']
        scenarios, reasons = matched_frame_scenarios(data, config)
        self.assertEqual(scenarios, [])
        self.assertTrue(reasons)

    def test_correct_regional_identity_is_accepted(self):
        _, data, config = with_regions()
        scenarios, reasons = matched_frame_scenarios(data, config)
        self.assertFalse(reasons)
        self.assertTrue(scenarios)
        self.assertIn('서울특별시', scenarios[0]['regional_frame_logit_change'])

    def test_absent_regional_observation_keeps_explicit_fallback(self):
        _, data, config = with_regions()
        data['polls'] = data['polls'][:2]
        scenarios, reasons = matched_frame_scenarios(data, config)
        self.assertFalse(reasons)
        self.assertTrue(scenarios)
        details = scenarios[0]['regional_observation_details']['서울특별시']
        self.assertEqual(details['baseline']['weight'], 0)
        self.assertEqual(details['current']['weight'], 0)

    def test_party_support_is_still_fully_ignored(self):
        districts, data, config = inputs()
        before = build_report(districts, data, config, draws=100)
        changed = copy.deepcopy(data)
        changed['polls'].append({'question_type': 'party_support',
                                'poll_id': 'new', 'published_at': '2099-99-99',
                                'shares': {DEM: 999, CON: -900}})
        self.assertEqual(before, build_report(districts, changed, config, draws=100))
        changed['polls'][-1]['shares'] = {DEM: .99, CON: .01}
        self.assertEqual(before, build_report(districts, changed, config, draws=100))
        changed['polls'].pop()
        self.assertEqual(before, build_report(districts, changed, config, draws=100))


if __name__ == '__main__':
    unittest.main()
