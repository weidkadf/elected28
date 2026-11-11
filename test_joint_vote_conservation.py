"""Synthetic joint-conservation invariants; no election data are loaded."""

import copy
from itertools import product
import unittest

from scripts.validate_joint_vote_conservation import (
    FALSE_FLAGS, build_report, build_synthetic_report, validate_joint_conservation,
)


class JointVoteConservationTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{"source_district": "S", "party_original": "P", "candidate": "C",
                         "fixed_named_ward": 10, "unlocated": 4}]
        self.targets = ["A", "B"]
        self.edges = [["S", "A"], ["S", "B"]]
        self.rows = [dict(self.sources[0], target_district="A", fixed_named_ward=6, unlocated=1),
                     dict(self.sources[0], target_district="B", fixed_named_ward=4, unlocated=3)]

    def check(self, sources=None, targets=None, edges=None, rows=None, **kwargs):
        return validate_joint_conservation(
            self.sources if sources is None else sources,
            self.targets if targets is None else targets,
            self.edges if edges is None else edges,
            self.rows if rows is None else rows, **{"synthetic_only": True, **kwargs})

    def test_01_valid_split_preserves_both_categories(self):
        before = copy.deepcopy((self.sources, self.targets, self.edges, self.rows))
        report = self.check()
        self.assertEqual(report["source_totals"], {"fixed_named_ward": 10, "unlocated": 4})
        self.assertEqual(report["source_totals"], report["allocated_totals"])
        self.assertEqual(before, (self.sources, self.targets, self.edges, self.rows))

    def test_02_report_has_three_fixtures_and_no_real_approval(self):
        report = build_report()
        self.assertEqual(report, build_synthetic_report())
        self.assertEqual(report["status"], "ARITHMETIC_PASS_SYNTHETIC_ONLY")
        self.assertIs(report["arithmetic_pass"], True)
        self.assertIs(report["synthetic_only"], True)
        for flag in FALSE_FLAGS:
            self.assertIs(report[flag], False)
        for field in ("real_allocations_checked", "geographic_crosswalk_eligible_districts",
                      "historical_backtests_executed"):
            self.assertEqual(report[field], 0)
        self.assertEqual((report["synthetic_case_count"], report["valid_case_count"],
                          report["invalid_cases_rejected"]), (3, 1, 2))

    def test_03_explicit_true_required(self):
        for value in (False, None, 0, 1, "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.check(synthetic_only=value)
        with self.assertRaises(ValueError):
            validate_joint_conservation(self.sources, self.targets, self.edges, self.rows)

    def test_04_fixed_votes_cannot_be_duplicated(self):
        with self.assertRaises(ValueError):
            self.check(rows=[dict(row, fixed_named_ward=10) for row in self.rows])

    def test_05_unlocated_votes_cannot_be_duplicated(self):
        with self.assertRaises(ValueError):
            self.check(rows=[dict(row, unlocated=4) for row in self.rows])

    def test_06_vote_categories_cannot_compensate(self):
        rows = copy.deepcopy(self.rows)
        rows[0].update(fixed_named_ward=5, unlocated=2)
        with self.assertRaises(ValueError):
            self.check(rows=rows)

    def test_07_candidates_and_original_parties_cannot_compensate(self):
        for changed in ({"candidate": "D"}, {"party_original": "Q"}):
            sources = self.sources + [dict(self.sources[0], **changed)]
            rows = copy.deepcopy(self.rows) + [dict(row, **changed) for row in self.rows]
            rows[0]["unlocated"] = 2
            rows[2]["unlocated"] = 0
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.check(sources=sources, rows=rows)

    def test_08_source_districts_cannot_compensate(self):
        sources = self.sources + [dict(self.sources[0], source_district="T")]
        edges = self.edges + [["T", "A"], ["T", "B"]]
        rows = copy.deepcopy(self.rows) + [dict(row, source_district="T") for row in self.rows]
        rows[0]["fixed_named_ward"] += 1
        rows[2]["fixed_named_ward"] -= 1
        with self.assertRaises(ValueError):
            self.check(sources=sources, edges=edges, rows=rows)

    def test_09_unknown_candidate_or_party_rejected(self):
        for field in ("candidate", "party_original"):
            rows = [dict(self.rows[0], **{field: "unknown"}), self.rows[1]]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(rows=rows)

    def test_10_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            self.check(rows=[dict(self.rows[0], source_district="unknown"), self.rows[1]])

    def test_11_unknown_target_rejected(self):
        with self.assertRaises(ValueError):
            self.check(rows=[dict(self.rows[0], target_district="unknown"), self.rows[1]])

    def test_12_disallowed_or_invalid_edges_rejected(self):
        for edges in ([self.edges[0]], [], self.edges + [self.edges[0]],
                      [["unknown", "A"]], [["S", "unknown"]], [["S"]]):
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                self.check(edges=edges)

    def test_13_duplicate_source_identity_rejected(self):
        with self.assertRaises(ValueError):
            self.check(sources=self.sources * 2)

    def test_14_duplicate_allocation_or_target_rejected(self):
        with self.assertRaises(ValueError):
            self.check(rows=self.rows + [dict(self.rows[0])])
        with self.assertRaises(ValueError):
            self.check(targets=self.targets + ["A"])

    def test_15_negative_votes_rejected(self):
        for field in ("fixed_named_ward", "unlocated"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(rows=[dict(self.rows[0], **{field: -1}), self.rows[1]])
            with self.assertRaises(ValueError):
                self.check(sources=[dict(self.sources[0], **{field: -1})])

    def test_16_noninteger_votes_and_unexpected_fields_rejected(self):
        for value in (True, 1.0, "1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.check(rows=[dict(self.rows[0], unlocated=value), self.rows[1]])
        with self.assertRaises(ValueError):
            self.check(sources=[dict(self.sources[0], party_support=50)])
        row = dict(self.rows[0])
        del row["unlocated"]
        with self.assertRaises(ValueError):
            self.check(rows=[row, self.rows[1]])

    def test_17_missing_source_candidate_is_not_assumed_zero(self):
        sources = self.sources + [dict(self.sources[0], candidate="zero", fixed_named_ward=0, unlocated=0)]
        with self.assertRaises(ValueError):
            self.check(sources=sources)

    def test_18_missing_target_is_not_assumed_zero(self):
        with self.assertRaises(ValueError):
            self.check(rows=[dict(self.sources[0], target_district="A")])

    def test_19_explicit_zero_rows_are_valid(self):
        rows = [dict(self.sources[0], target_district="A"),
                dict(self.sources[0], target_district="B", fixed_named_ward=0, unlocated=0)]
        self.assertTrue(self.check(rows=rows)["arithmetic_pass"])
        sources = [dict(self.sources[0], fixed_named_ward=0, unlocated=0)]
        rows = [dict(sources[0], target_district=target) for target in self.targets]
        self.assertTrue(self.check(sources=sources, rows=rows)["arithmetic_pass"])

    def test_20_exhaustive_81_combinations_only_nine_conserve(self):
        sources = [dict(self.sources[0], fixed_named_ward=2, unlocated=2)]
        checked = accepted = 0
        for fixed_a, fixed_b, unknown_a, unknown_b in product(range(3), repeat=4):
            rows = [dict(sources[0], target_district="A", fixed_named_ward=fixed_a, unlocated=unknown_a),
                    dict(sources[0], target_district="B", fixed_named_ward=fixed_b, unlocated=unknown_b)]
            expected = fixed_a + fixed_b == 2 and unknown_a + unknown_b == 2
            checked += 1
            try:
                self.check(sources=sources, rows=rows)
                actual = True
                accepted += 1
            except ValueError:
                actual = False
            self.assertEqual(actual, expected)
        self.assertEqual((checked, accepted), (81, 9))


if __name__ == "__main__":
    unittest.main()
