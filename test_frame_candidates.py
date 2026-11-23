import csv, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
import scan_nesdc_frame_candidates as F  # noqa: E402

ARS_Q = """Q8. 다음 중 어느 정당을 지지하십니까?
① 더불어민주당이면 1)번을,
Q9. 마지막으로 2028년 4월에 국회의원 선거가 있습니다. 어떤 결과가 나오기를 더 바라십니까?
① 현 정부의 국정 운영을 뒷받침하기 위해 여당이 더 많이 당선되어야 한다 면 1)번을,
② 현 정부의 견제를 위해 야당이 더 많이 당선되어야 한다 면 2)번을,
③ 기타 이면 3)번을,
④ 잘 모르겠다면 4)번을 눌러주세요.
90) 감사합니다."""
CATI_Q = """문 4) 다음 국회의원 선거는 내후년 4월 치러집니다. 어느 쪽 의견에 더 동의하십니까?
(1, 2를 읽어줄 것, Rotation)
1. 현 정부를 지원하기 위해
여당 후보가 많이 당선돼야 한다
2. 현 정부를 견제하기 위해
야당 후보가 많이 당선돼야 한다
9. 모름/응답거절
문 5) 호감이 가십니까?"""
TABLE = """문8) 다음 국회의원 선거에서 어떤 결과가 나오기를 더 바라십니까?
                     ① 현 정부의 국정 운영을 뒷받침  ② 현 정부의 견제를 위해  ③ 기타  ④ 잘모름
            조사   가중값
            완료   적용
 전체         1,002 1,002 37.0     52.0     8.4      2.6
     남자     547  496    36.8     54.0     7.4      1.8
     서울     208  186    34.9     51.8     10.6     2.7
 광역지역별    인천/경기   286  326    39.2     49.5     7.8      3.6
     호남권     99   96    52.8     34.0     12.2     1.0"""


class ParseTests(unittest.TestCase):
    def test_ars_questionnaire(self):
        q, opts = F.find_question(ARS_Q)
        self.assertTrue(q.startswith('Q9.'))
        self.assertEqual([F.role(o) for o in opts], ['support', 'check', 'other', 'other'])
        self.assertEqual(opts[2], '기타')

    def test_wrapped_cati_options(self):
        q, opts = F.find_question(CATI_Q)
        self.assertEqual(opts[0], '현 정부를 지원하기 위해 여당 후보가 많이 당선돼야 한다')
        self.assertEqual([F.role(o) for o in opts], ['support', 'check', 'other'])

    def test_opposition_judgment_points_to_support(self):
        self.assertEqual(F.role('야당을 심판해야 한다'), 'support?')
        self.assertEqual(F.role('정부ㆍ여당을 심판해야 한다'), 'check')

    def test_table_rows(self):
        opts = ['s', 'c', 'o', 'd']
        t = F.read_table(TABLE, opts)
        self.assertEqual(t['national_label'], '전체')
        self.assertEqual(list(t['national'].values()), [37.0, 52.0, 8.4, 2.6])
        self.assertEqual(t['national_n'], 1002.0)
        self.assertEqual(t['regions']['광주/전라'], {'shares': [52.8, 34.0, 12.2, 1.0], 'n': 96.0})
        self.assertEqual(t['regions']['인천/경기']['n'], 326.0)

    def test_unrelated_page_is_skipped(self):
        self.assertIsNone(F.read_table('1. 대통령 직무평가\n 잘함 잘못함\n 전체 1,000 1,000 40.0 55.0 5.0', ['s', 'c', 'o']))

    def test_split_counts_do_not_become_shares_or_a_national_row(self):
        opts = ['s', 'c', 'o']
        title = '정부 지원론 vs 견제론'
        region = '부산/울산/경남  1 49  1 47    31% 55% 13%    42 56'
        sex = '남성  4 95  4 96    35% 49% 16%'
        self.assertIsNone(F.split_row('부산/울산/경남  1 49  1 47', 3))
        self.assertIsNone(F.read_table('\n'.join([title, region, sex]), opts))
        prior = '10월 3주(13~15일)  1 ,003  1 ,003   34% 47% 18%'
        current = '11월 3주(17~19일)  1 ,001  1 ,001   37% 47% 16%'
        text = '\n'.join([title, prior, current, region, sex])
        t = F.read_table(text, opts, fieldwork_end='2026-11-19')
        self.assertEqual(t['national_label'], '11월 3주(17~19일)')
        self.assertEqual(t['national'], dict(zip(opts, [37, 47, 16])))
        self.assertEqual(t['national_n'], 1001)
        self.assertEqual(t['regions']['부산/울산/경남'], {'shares': [31, 55, 13], 'n': 147})
        self.assertIsNone(F.read_table(text, opts, fieldwork_end='2026-11-26'))
        total_page = '\f' + title + '\n전국   1,001 1,001   37% 47% 16%'
        self.assertEqual(F.read_table(text + total_page, opts)['national_label'], '전국')
        self.assertEqual(F.split_row('전체 1,001 1,001 37 47 16', 3), ('전체', [37, 47, 16], [1001, 1001]))


class ReviewListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = json.loads((ROOT / 'outputs/frame_candidates.json').read_text(encoding='utf-8'))['candidates']
        cls.s = json.loads((ROOT / 'data/nesdc/frame_scan_state.json').read_text(encoding='utf-8'))

    def test_candidates_are_well_formed(self):
        for c in self.c:
            self.assertNotIn('여론조사꽃', c['pollster'])
            self.assertTrue(any(r.startswith('support') for r in c['option_roles']) and 'check' in c['option_roles'])
            if c['status'] == 'parsed':
                self.assertAlmostEqual(sum(c['table']['national'].values()), 100, delta=3)

    def test_excluded_pollster_never_scanned(self):
        for p in self.s['polls'].values():
            if '여론조사꽃' in p['pollster']: self.assertEqual(p['status'], 'excluded_pollster')

    def test_review_list_matches_hand_entries(self):
        reg = [p for path in F.REGISTRIES for p in json.loads(path.read_text(encoding='utf-8'))['polls']
               if p['scope'] == 'national']
        for c in self.c:
            if c['status'] != 'parsed':
                continue
            key = F.pkey(c['pollster'], c['fieldwork_end'])
            matches = [p for p in reg if str(p.get('nesdc_reg_no')) == str(c['reg_no'])
                       or F.pkey(p['pollster'], p['fieldwork_end']) == key]
            shares = c['table']['national']
            nat = {role: shares[option] for role, option in zip(c['option_roles'], c['options'])}
            for p in matches:
                with self.subTest(reg_no=c['reg_no'], poll_id=p['poll_id']):
                    self.assertAlmostEqual(nat['support'], p['shares']['support'] * 100, delta=0.6)
                    self.assertAlmostEqual(nat['check'], p['shares']['check'] * 100, delta=0.6)

    def test_gallup_683_artifacts_agree(self):
        c = next(c for c in self.c if c['reg_no'] == 17369)
        self.assertEqual(c['registered_in'], 'frame_polls_multi.json')
        self.assertEqual(c['table'], self.s['polls']['17369']['table'])
        self.assertEqual(c['table']['national_label'], '11월 3주(17~19일)')
        self.assertEqual(list(c['table']['national'].values()), [37, 47, 16])


VOTE_Q = """(지지 정당)
Q1. 선생님께서는 2028년 총선에서 다음 중 어느 정당 후보에게 투표하실 생각입니까?
호명순서는 가나다순입니다.
1)번 개혁신당 2)번 국민의힘 3)번 더불어민주당
4)번 조국혁신당 5)번 진보당 6)번 기타 정당
7)번 없다 8)번 잘 모르겠다
Q2. 절대 찍고 싶지 않은 정당은 어디입니까? 2028년 총선에서 어느 정당 후보에게 투표하지 않겠습니까?
1)번 개혁신당 2)번 국민의힘 3)번 더불어민주당"""
ARS_VOTE_Q = """문5. 내일이 국회의원 총선거라면 선생님께서는 다음 중 어느 정당 후보에게 투표하시겠습니까?
① 더불어민주당 후보면 1번
② 국민의힘 후보면 2번
③ 진보당 후보면 3번
④ 투표할 정당 후보가 없다면 4번
⑤ 잘 모르겠다면 5번을 눌러주세요"""


class VoteIntentionTests(unittest.TestCase):
    def test_inline_options(self):
        q, opts, kind = F.find_vote_question(VOTE_Q)
        self.assertTrue(q.startswith('Q1.'))
        self.assertEqual(opts, ['개혁신당', '국민의힘', '더불어민주당', '조국혁신당', '진보당', '기타 정당', '없다', '잘 모르겠다'])
        self.assertEqual(kind, 'unspecified')
        self.assertIsNone(F.find_question(VOTE_Q))

    def test_negative_question_skipped(self):
        self.assertIsNone(F.find_vote_question(VOTE_Q.split('Q2.')[0].replace('Q1.', 'Q9.').replace('투표하실', '절대 투표하지 않으실')))

    def test_party_mapping(self):
        q, opts, _ = F.find_vote_question(ARS_VOTE_Q)
        self.assertEqual([F.party_key(o) for o in opts], ['더불어민주당', '국민의힘', '진보당', '없음', '모름'])

    def test_collected_table(self):
        with (ROOT / 'outputs/vote_intention_2028.csv').open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            self.assertNotIn('여론조사꽃', r['pollster'])
            if r['status'] == 'auto_read':
                self.assertAlmostEqual(sum(float(r[k]) for k in F.PARTIES if r[k]), 100, delta=3)


if __name__ == '__main__':
    unittest.main()
