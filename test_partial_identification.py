"""Exact mathematical tests; diagnostic boxes do not certify geographic mapping."""
import copy
from fractions import Fraction
from itertools import product
import json
from pathlib import Path
import unittest

from scripts.partial_identification import candidate_envelope, build_report

ROOT = Path(__file__).resolve().parent


def partition(fixed, caps):
    return [{'party_original': '무소속', 'candidate': str(i), 'named_ward': l,
             'unlocated': u, 'total': l + u} for i, (l, u) in enumerate(zip(fixed, caps))]


class PartialIdentificationTests(unittest.TestCase):
    def test_exact_bounds_against_enumeration(self):
        for fixed in product(range(3), repeat=3):
            if not sum(fixed):
                continue
            for caps in product(range(3), repeat=3):
                report = candidate_envelope(partition(fixed, caps))
                possibilities = [tuple(l + x for l, x in zip(fixed, xs))
                                 for xs in product(*(range(u + 1) for u in caps))]
                for i, row in enumerate(report['candidate_envelopes']):
                    shares = [Fraction(v[i], sum(v)) for v in possibilities]
                    self.assertEqual(Fraction(*row['share_lower_exact']), min(shares))
                    self.assertEqual(Fraction(*row['share_upper_exact']), max(shares))

    def test_leader_flags_against_enumeration(self):
        for fixed in [(3, 2, 0), (1, 1, 1), (0, 0, 1)]:
            for caps in product(range(3), repeat=3):
                report = candidate_envelope(partition(fixed, caps))
                votes = [tuple(l + x for l, x in zip(fixed, xs))
                         for xs in product(*(range(u + 1) for u in caps))]
                for i, row in enumerate(report['candidate_envelopes']):
                    colead = [v[i] >= max(v[j] for j in range(3) if j != i) for v in votes]
                    strict = [v[i] > max(v[j] for j in range(3) if j != i) for v in votes]
                    self.assertEqual(row['possible_coleader_under_box'], any(colead))
                    self.assertEqual(row['possible_strict_leader_under_box'], any(strict))
                    self.assertEqual(row['guaranteed_strict_leader_under_box'], all(strict))

    def test_full_result_recovered_by_all_remainders(self):
        data = partition([20, 10, 5], [4, 9, 2])
        report = candidate_envelope(data)
        self.assertEqual(report['full_original_valid_votes'], 50)
        self.assertEqual([r['full_original_votes'] for r in report['candidate_envelopes']], [24, 19, 7])
        self.assertAlmostEqual(sum(r['full_original_vote_share'] for r in report['candidate_envelopes']), 1)

    def test_no_remainder_collapses_intervals(self):
        report = candidate_envelope(partition([4, 6], [0, 0]))
        self.assertTrue(all(r['share_lower'] == r['share_upper'] for r in report['candidate_envelopes']))

    def test_marginal_extrema_not_joint_vote_vector(self):
        report = candidate_envelope(partition([10, 10], [10, 10]))
        self.assertGreater(sum(r['share_upper'] for r in report['candidate_envelopes']), 1)
        self.assertLess(sum(r['share_lower'] for r in report['candidate_envelopes']), 1)
        self.assertFalse(report['joint_extrema_or_probability'])

    def test_ties_not_called_guaranteed_or_strict(self):
        report = candidate_envelope(partition([10, 5], [0, 5]))
        a, b = report['candidate_envelopes']
        self.assertFalse(a['guaranteed_strict_leader_under_box'])
        self.assertTrue(b['possible_coleader_under_box'])
        self.assertFalse(b['possible_strict_leader_under_box'])

    def test_independents_remain_separate_candidates(self):
        report = candidate_envelope(partition([2, 3, 4], [1, 2, 3]))
        self.assertEqual(len(report['candidate_envelopes']), 3)
        self.assertEqual(len({r['candidate'] for r in report['candidate_envelopes']}), 3)

    def test_scaling_preserves_bounds_and_leader_status(self):
        a = candidate_envelope(partition([7, 6, 1], [3, 4, 2]))
        b = candidate_envelope(partition([70, 60, 10], [30, 40, 20]))
        for x, y in zip(a['candidate_envelopes'], b['candidate_envelopes']):
            for key in ('share_lower_exact', 'share_upper_exact', 'guaranteed_strict_leader_under_box'):
                self.assertEqual(x[key], y[key])

    def test_order_is_reproducible(self):
        data = partition([2, 3], [1, 4])
        self.assertEqual(candidate_envelope(data), candidate_envelope(list(reversed(data))))

    def test_party_support_metadata_has_no_effect(self):
        data = partition([2, 3], [1, 4])
        expected = candidate_envelope(data)
        for row in data:
            row['party_support'] = {'invalid': 1e99}
        self.assertEqual(candidate_envelope(data), expected)

    def test_negative_float_bool_counts_rejected(self):
        for bad in (-1, 1.5, True):
            with self.subTest(bad=bad):
                data = partition([2, 3], [1, 4])
                data[0]['unlocated'] = bad
                with self.assertRaisesRegex(ValueError, 'nonnegative integers'):
                    candidate_envelope(data)

    def test_zero_fixed_target_rejected(self):
        with self.assertRaisesRegex(ValueError, 'positive fixed'):
            candidate_envelope(partition([0, 0], [1, 2]))

    def test_duplicate_identity_and_bad_partition_rejected(self):
        data = partition([2, 3], [1, 4])
        data.append(copy.deepcopy(data[0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            candidate_envelope(data)
        data = partition([2, 3], [1, 4])
        data[0]['total'] += 1
        with self.assertRaisesRegex(ValueError, 'reconcile'):
            candidate_envelope(data)

    def test_single_candidate_has_unit_share(self):
        row = candidate_envelope(partition([4], [2]))['candidate_envelopes'][0]
        self.assertEqual((row['share_lower'], row['share_upper']), (1, 1))

    def test_all_original_districts_are_diagnostic_only(self):
        data = json.loads((ROOT / 'data/history_2020/ward_readiness_253.json').read_text())
        report = build_report(data)
        self.assertEqual(report['diagnostic_district_count'], 253)
        self.assertEqual(report['full_original_valid_votes'], 28741408)
        self.assertEqual(sum(report['lead_status_counts'].values()), 253)
        for field in ('unknown_geography_solved', 'training_approved', 'current_model_linked',
                      'allocation_weights_created', 'joint_geographic_allocation_or_national_seat_bounds'):
            self.assertFalse(report[field])
        self.assertTrue(all(d['target_district_2024'] is None for d in report['districts']))

    def test_incomplete_district_inventory_rejected(self):
        with self.assertRaisesRegex(ValueError, '253'):
            build_report([])


if __name__ == '__main__':
    unittest.main()
