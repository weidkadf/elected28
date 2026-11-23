import csv
import unittest

from scripts import backtest_2020_2024 as B


class BacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, _, cls.x_by_scope, *_ = B.run()

    def test_loro_parameters_and_predictions_ignore_held_outcomes(self):
        scope = '서울'
        original = next(r for r in B.evaluate_loro(self.rows, self.x_by_scope, 0.12) if r['scope'] == scope)
        shifted = [dict(r, y=r['y'] + 1.0) if r['scope'] == scope else r for r in self.rows]
        same_scores = next(r for r in B.evaluate_loro(shifted, self.x_by_scope, 0.12) if r['scope'] == scope)
        self.assertEqual(same_scores, original)
        changed_outcomes = [dict(r, p24=0.99) if r['scope'] == scope else r for r in shifted]
        changed_scores = next(r for r in B.evaluate_loro(changed_outcomes, self.x_by_scope, 0.12) if r['scope'] == scope)
        self.assertEqual(changed_scores['training_fit'], original['training_fit'])
        self.assertEqual(changed_scores['dem_seats_mean'], original['dem_seats_mean'])
        self.assertEqual(changed_scores['n'], original['n'])
        self.assertNotEqual(changed_scores['p10_p90_coverage'], original['p10_p90_coverage'])

    def test_independents_are_retained_as_separate_candidates(self):
        district = next(r for r in self.rows if r['district_id'] == '2024-30-대덕구')
        with (B.ROOT / 'data/history_2020/verified_candidates_2020.csv').open(encoding='utf-8-sig') as f:
            original = [r for r in csv.DictReader(f) if r['province'] == '대전광역시' and r['district'] == '대덕구']
        independent_votes = {r['candidate']: int(r['votes']) for r in original if r['party_original'] == '무소속'}
        self.assertEqual(sorted(independent_votes.values()), [496, 2913])
        shares = {candidate: share for (party, candidate), share in district['shares20'].items() if party == '무소속'}
        valid = int(original[0]['valid_votes'])
        self.assertEqual(shares, {candidate: votes / valid for candidate, votes in independent_votes.items()})
        self.assertEqual(max(shares.values()), 2913 / valid)


if __name__ == '__main__':
    unittest.main()
