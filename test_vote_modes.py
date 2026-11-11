import copy
import unittest
from scripts.build_2020_vote_modes import parse_rows, classify, SPECIAL, JOINT, build_report

def row(n, a, b, votes):
    return n, {'A': a, 'B': b, 'C': str(votes), 'D': str(votes), 'E': str(votes),
               'BC': str(votes), 'BD': '0', 'BE': '0'}

def fixture():
    return [row(i, label, '', 0) for i, label in enumerate(sorted(SPECIAL), 8)] + [
        row(13, '가동', '소계', 5), row(14, '', '관내사전투표', 2), row(15, '', '가동제1투', 3)]

class VoteModeTests(unittest.TestCase):
    def parse(self, rows):
        return parse_rows(rows, {'E': ('정당', '후보')})
    def test_valid_partition(self):
        parents, children, special = self.parse(fixture())
        self.assertEqual((len(parents), len(children), len(special)), (1, 2, 5))
        self.assertEqual(sum(x['votes'][('정당', '후보')] for x in children), 5)
    def test_classification(self):
        self.assertEqual(classify(JOINT), 'joint_station_label')
        for name in ['옥천동투표소', '탑·대성동제1투']:
            self.assertEqual(classify(name), 'ordinary_station_label')
    def test_unknown_label(self):
        with self.assertRaises(ValueError): classify('알수없음')
    def test_duplicate_row(self):
        x = fixture(); x.append(copy.deepcopy(x[-1]))
        with self.assertRaises(ValueError): self.parse(x)
    def test_duplicate_child(self):
        x = fixture(); x.append(row(16, '', '가동제1투', 3))
        with self.assertRaises(ValueError): self.parse(x)
    def test_missing_advance(self):
        x = fixture(); x[-2][1]['B'] = '가동제2투'
        with self.assertRaises(ValueError): self.parse(x)
    def test_orphan(self):
        x = fixture(); del x[5]
        with self.assertRaises(ValueError): self.parse(x)
    def test_parent_mismatch(self):
        x = fixture(); x[-1] = row(15, '', '가동제1투', 4)
        with self.assertRaises(ValueError): self.parse(x)
    def test_negative_votes(self):
        x = fixture(); x[-1][1]['E'] = '-1'
        with self.assertRaises(ValueError): self.parse(x)
    def test_original_controls_and_gates(self):
        r = build_report()
        self.assertEqual(r['national_valid_votes'], 28741408)
        self.assertEqual(r['child_rows'], 17815)
        self.assertEqual(r['district_count'], 253)
        for field in ['geography_approved', 'residence_assignment_verified', 'allocation_generated',
                      'backtest_executed', 'current_model_linked', 'party_support_used']:
            self.assertIs(r[field], False)
        for child in r['children']:
            self.assertEqual(sum(x['votes'] for x in child['candidate_votes']), child['metrics']['valid'])

if __name__ == '__main__': unittest.main()
