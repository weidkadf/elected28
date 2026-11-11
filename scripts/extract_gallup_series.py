#!/usr/bin/env python3
"""Build data/history_polls/gallup_series_v030.json from archived Gallup PDFs.

* Quarterly presidential approval table (1988-2024) is parsed from the text layer of
  gallup_580_20240329.pdf (requires `pdftotext`, poppler-utils).
* Monthly/weekly "총선 결과 기대" trend points (2019-2024) are visual transcriptions of the
  chart on PDF page 14 of the same report; they are cross-checked against the separately
  archived weekly reports 392/394/395/578/579/580 and the build fails on any mismatch.
* Weekly approval for the paired frame surveys: 2024 from the 578-580 text layer, 2020 from
  visual transcription of page 6 of 392/394/395, 2026 from the official 678 HTML.
No party-support values are extracted.
"""
from __future__ import annotations
import hashlib, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HP = ROOT / 'data' / 'history_polls'
OUT = HP / 'gallup_series_v030.json'
PRESIDENTS = ['노태우', '김영삼', '김대중', '노무현', '이명박', '박근혜', '문재인', '윤석열']

# chart on 580 p.14 (fieldwork end date, support%, check%) -- visual transcription
TREND_22 = [('2022-12-01',36,49),('2023-03-02',42,44),('2023-04-06',36,50),('2023-05-04',37,49),
            ('2023-06-01',37,49),('2023-07-06',38,50),('2023-08-03',36,48),('2023-09-07',37,50),
            ('2023-10-12',39,48),('2023-11-09',40,46),('2023-12-07',35,51),('2024-01-11',35,51),
            ('2024-03-14',40,49),('2024-03-21',36,51),('2024-03-28',40,49)]
TREND_21 = [('2019-04-11',47,37),('2019-05-09',46,39),('2019-06-05',47,40),('2020-01-09',49,37),
            ('2020-02-13',43,45),('2020-03-12',43,43),('2020-03-26',46,40),('2020-04-02',47,37),
            ('2020-04-08',51,40),('2020-04-14',49,39)]
# weekly approval (approve%, disapprove%) paired with the same survey's frame item
WEEKLY_APPROVAL = {
    'gallup_392': {'fieldwork_end':'2020-03-12','approve':49,'disapprove':45,'evidence':'392 PDF p6 chart, visual'},
    'gallup_394': {'fieldwork_end':'2020-03-26','approve':55,'disapprove':39,'evidence':'394 PDF p6 chart, visual'},
    'gallup_395': {'fieldwork_end':'2020-04-02','approve':56,'disapprove':36,'evidence':'395 PDF p6 chart, visual'},
    'gallup_578': {'fieldwork_end':'2024-03-14','approve':36,'disapprove':57,'evidence':'578 PDF text layer'},
    'gallup_579': {'fieldwork_end':'2024-03-21','approve':34,'disapprove':58,'evidence':'579 PDF text layer'},
    'gallup_580': {'fieldwork_end':'2024-03-28','approve':34,'disapprove':58,'evidence':'580 PDF text layer'},
    'gallup_678': {'fieldwork_end':'2026-10-15','approve':39,'disapprove':52,
                   'evidence':'official HTML https://www.gallup.co.kr/gallupdb/reportContent.asp?seqNo=1662 (2026-11-05)'},
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def quarterly_table(pdf):
    text = subprocess.run(['pdftotext', '-layout', str(pdf), '-'], capture_output=True, text=True, check=True).stdout
    rows = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for name in PRESIDENTS:
            m = re.search(r'\d+대\s+' + name + r'\s+긍정\s+(.*)$', line)
            if m and name not in rows:
                neg = re.search(r'부정\s+(.*)$', lines[i + 1])
                parse = lambda s: [None if t == '-' else int(t) for t in s.split()]
                rows[name] = {'approve': parse(m.group(1)), 'disapprove': parse(neg.group(1))}
    if set(rows) != set(PRESIDENTS):
        raise SystemExit('quarterly table parse incomplete: ' + str(sorted(rows)))
    return rows


def crosscheck():
    """Chart transcription must match every separately archived weekly report."""
    trend = {d: (s, c) for d, s, c in TREND_21 + TREND_22}
    for f in sorted(HP.glob('gallup_*_frame_observations.json')):
        for p in json.loads(f.read_text(encoding='utf-8'))['polls']:
            if p['scope'] != 'national':
                continue
            got = trend.get(p['fieldwork_end'])
            want = (round(p['shares']['정부지원'] * 100), round(p['shares']['정부견제'] * 100))
            if got != want:
                raise SystemExit(f'trend transcription mismatch {f.name}: {got} vs {want}')
    return True


def main():
    pdf = HP / 'gallup_580_20240329.pdf'
    out = {
        'schema_version': 'gallup_series_v030_1',
        'source_pdf': str(pdf.relative_to(ROOT)), 'source_pdf_sha256': sha(pdf),
        'party_support_included': False,
        'quarterly_approval_tenure': {
            'definition': '재임 분기(취임일 기준) 긍정/부정률. 1988~2011 분기 중위수, 2012~ 주간 분기 통합 (원문 각주)',
            'evidence': 'gallup_580_20240329.pdf 텍스트 레이어 파싱',
            'rows': quarterly_table(pdf)},
        'frame_trend': {
            'evidence': 'gallup_580_20240329.pdf 14쪽 차트 시각 전사; 392/394/395/578/579/580 주간 원문과 일치 검사 통과',
            'note': '2024년 1월 말~3월 초는 3구도 질문이라 원문 차트에서 제외됨. 2020-04-08·04-14는 공표금지 기간 조사로 선거 전 공표 자료가 아님(추세 분산 추정에만 사용).',
            'cycle_21': {'governing_party': '더불어민주당', 'opposition_party': '미래통합당', 'democratic_component': 'support',
                         'election_date': '2020-04-15',
                         'points': [{'fieldwork_end': d, 'support': s / 100, 'check': c / 100} for d, s, c in TREND_21]},
            'cycle_22': {'governing_party': '국민의힘', 'opposition_party': '더불어민주당', 'democratic_component': 'check',
                         'election_date': '2024-04-10',
                         'points': [{'fieldwork_end': d, 'support': s / 100, 'check': c / 100} for d, s, c in TREND_22]}},
        'weekly_approval_paired': WEEKLY_APPROVAL,
        'crosscheck_passed': crosscheck(),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(OUT.relative_to(ROOT)), 'presidents': len(out['quarterly_approval_tenure']['rows'])}, ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())
