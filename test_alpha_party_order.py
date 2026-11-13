"""identify_alpha: 민주/국힘 column order read from the table header (two-line '더불어/민주당' headers, 조국혁신당 columns)."""
import json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
import identify_alpha as I  # noqa: E402


class PartyOrderTests(unittest.TestCase):
    def test_header_order(self):
        self.assertTrue(I.party_order_from_header('조사 가중값 더불어 국민의힘 조국 개혁신당 진보당 계 완료 적용 민주당 혁신당'))
        self.assertFalse(I.party_order_from_header('국민의힘 더불어민주당 조국혁신당'))
        self.assertIsNone(I.party_order_from_header('이재명 김문수 이준석'))

    def test_swap(self):
        polls = [{'reg': 'x', 'xtabs': [{'page': 1, 'title': '더불어 국민의힘 조국 / 민주당 혁신당',
                                         'tot': {'C': 46.0, 'D': 32.0}, 'n': 1000, 'rows': {'s': {'C': 82.0, 'D': 5.0, 'n': 338.0}}}]}]
        self.assertEqual(I.fix_party_order(polls), [{'reg': 'x', 'page': 1}])
        t = polls[0]['xtabs'][0]
        self.assertEqual((t['tot']['D'], t['tot']['C']), (46.0, 32.0))
        self.assertEqual((t['rows']['s']['D'], t['rows']['s']['C']), (82.0, 5.0))

    def test_committed_output(self):
        m = json.loads((ROOT / 'outputs/alpha_identification.json').read_text(encoding='utf-8'))['micro']
        self.assertGreaterEqual(m['n_polls'], 88)
        for p in m['polls']:
            self.assertGreater(p['v_dem_side'] - p['v_other_side'], 0.3)


    def test_jk_added_to_dem_side(self):
        a = json.loads((ROOT / 'outputs/alpha_identification.json').read_text(encoding='utf-8'))['micro']
        jk = json.loads((ROOT / 'data/nesdc/frame_xtab_jk.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(a['jk']['tables_with_jk_added'], 85)
        self.assertLessEqual(len(jk['unread']), 3)
        # 리서치뷰 17348 문8 교차표, checked by hand against the PDF: 조국혁신당 8.6 / 지원론 9.1 / 심판론 6.5
        self.assertEqual(jk['tables']['17348:8:31.6:36.9']['J'], {'tot': 8.6, 's': 9.1, 'c': 6.5})
        p = next(p for p in a['polls'] if p['reg'] == '17348')
        self.assertEqual(p['jk_in_dem'], {'tot': 8.6, 's': 9.1, 'c': 6.5})


if __name__ == '__main__':
    unittest.main()
