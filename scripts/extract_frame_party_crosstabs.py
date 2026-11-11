#!/usr/bin/env python3
"""Extract Gallup frame-by-party crosstab rows and turnout-intention rows (v0.3.1).

For every archived Gallup report with the 총선 결과 기대 item, read from the PDF text layer:
  전체 row and the 더불어민주당 / 국민의힘(미래통합당) / 무당층 rows of the frame table
  (weighted n, support %, check %, don't-know %). The remaining parties are kept as a residual
  group derived from 전체 minus the listed rows, so the cells always add up to the published totals.
Turnout intention ('꼭 투표할 것이다') by the same groups is read from 394/395 (2020; the 2024
archive and 678 did not ask it). Requires pdftotext. Output: data/history_polls/frame_party_crosstabs.json
"""
from __future__ import annotations
import hashlib, json, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HP = ROOT / 'data' / 'history_polls'
WAVES = {
    '392': ('gallup_392_20200313.pdf', '미래통합당', '2020-03-12', '더불어민주당'),
    '394': ('gallup_394_20200327.pdf', '미래통합당', '2020-03-26', '더불어민주당'),
    '395': ('gallup_395_20200403.pdf', '미래통합당', '2020-04-02', '더불어민주당'),
    '578': ('gallup_578_20240315.pdf', '국민의힘', '2024-03-14', '국민의힘'),
    '579': ('gallup_579_20240322.pdf', '국민의힘', '2024-03-21', '국민의힘'),
    '580': ('gallup_580_20240329.pdf', '국민의힘', '2024-03-28', '국민의힘'),
    '662': ('gallup_662_20260501.pdf', '국민의힘', '2026-04-30', '더불어민주당'),
    '663': ('gallup_663_20260515.pdf', '국민의힘', '2026-05-14', '더불어민주당'),
    '664': ('gallup_664_20260522.pdf', '국민의힘', '2026-05-21', '더불어민주당'),
    '678': ('gallup_678_20261016.pdf', '국민의힘', '2026-10-15', '더불어민주당'),
}
ROW = r'{name}\s+([\d,]+)\s+([\d,]+)\s+(\d+)%\s+(\d+)%\s+(\d+)%'


def text(pdf):
    return subprocess.run(['pdftotext', '-layout', str(pdf), '-'], capture_output=True, text=True, check=True).stdout


def last_match(line, name):
    m = list(re.finditer(ROW.format(name=re.escape(name)), line))
    return m[-1] if m else None


def section(lines, header_pat, span=70):
    for i, l in enumerate(lines):
        if re.search(header_pat, l) and '사례수' not in l:
            # the table header row follows within a few lines
            for j in range(i, min(i + 8, len(lines))):
                if '사례수' in lines[j]:
                    return lines[j:j + span]
    return []


def frame_rows(lines, con):
    sec = section(lines, r'(국회의원선거|총선) 결과 기대\s*$')
    if not sec:
        idx = next(i for i, l in enumerate(lines) if '조사완료' in l and ('국회의원선거 결과 기' in l or '지방선거 결과 기대' in l))
        sec = lines[idx:idx + 70]
    out = {}
    for key, name in [('total', '전체'), ('dem', '더불어민주당'), ('con', con), ('independent', '무당\\(無黨\\)층')]:
        for l in sec:
            m = last_match(l, name.replace('\\(', '(').replace('\\)', ')')) if key != 'independent' else \
                list(re.finditer(r'무당\(無黨\)층\s+([\d,]+)\s+([\d,]+)\s+(\d+)%\s+(\d+)%\s+(\d+)%', l))
            if key == 'independent':
                m = m[-1] if m else None
            if m:
                out[key] = {'n_weighted': int(m.group(2).replace(',', '')), 'support': int(m.group(3)) / 100,
                            'check': int(m.group(4)) / 100, 'dk': int(m.group(5)) / 100}
                break
    return out


def trend_total(lines, end, want):
    """392 prints the national value only inside its trend block: take the row of this fieldwork."""
    day = int(end[-2:])
    for l in lines:
        for m in re.finditer(rf'~{day}일\)\s+([\d,]+)\s+([\d,]+)\s+(\d+)%\s+(\d+)%\s+(\d+)%', l):
            row = {'n_weighted': int(m.group(2).replace(',', '')), 'support': int(m.group(3)) / 100,
                   'check': int(m.group(4)) / 100, 'dk': int(m.group(5)) / 100, 'source_row': 'trend_block_row'}
            if (row['support'], row['check']) == want:
                return row
    raise SystemExit(f'trend row for {end} not found')


def turnout_rows(lines, con):
    sec = section(lines, r'국회의원선거 투표 의향\s*$', 45)
    out = {}
    for key, name in [('total', '전체'), ('dem', '더불어민주당'), ('con', con), ('independent', '무당(無黨)층')]:
        for l in sec:
            m = re.search(re.escape(name) + r'\s+([\d,]+)\s+([\d,]+)\s+(\d+)%', l)
            if m:
                out[key] = {'n_weighted': int(m.group(2).replace(',', '')), 'certain_to_vote': int(m.group(3)) / 100}
                break
    return out


def archived_national(w):
    f = HP / f'gallup_{w}_frame_observations.json'
    if not f.exists() and (HP / f'gallup_{w}_local_frame.json').exists():
        f = HP / f'gallup_{w}_local_frame.json'
    if f.exists():
        polls = json.loads(f.read_text(encoding='utf-8'))['polls']
    else:
        polls = [p for p in json.loads((ROOT / 'data/polls.json').read_text(encoding='utf-8'))['polls']
                 if p['poll_id'] == f'gallup_{w}_frame_national']
    p = next(p for p in polls if p['scope'] == 'national')
    return (round(p['shares']['정부지원'], 2), round(p['shares']['정부견제'], 2))


def main():
    res = {'schema_version': 'frame_party_crosstabs_1',
           'note': 'Party support used only to define turnout-weighting groups (user decision 2026-11-11).',
           'waves': {}}
    for w, (pdf, con, end, governing) in WAVES.items():
        p = HP / pdf
        lines = text(p).splitlines()
        fr = frame_rows(lines, con)
        want = archived_national(w)
        if 'total' not in fr or (round(fr['total']['support'], 2), round(fr['total']['check'], 2)) != want:
            fr['total'] = trend_total(lines, end, want)
        if (round(fr['total']['support'], 2), round(fr['total']['check'], 2)) != want:
            raise SystemExit(f'{w}: national total {fr["total"]} does not match archived {want}')
        missing = {'total', 'dem', 'con', 'independent'} - set(fr)
        if missing:
            raise SystemExit(f'{w}: frame rows missing {missing}')
        tot = fr['total']
        resid_n = tot['n_weighted'] - sum(fr[k]['n_weighted'] for k in ('dem', 'con', 'independent'))
        rs = tot['n_weighted'] * tot['support'] - sum(fr[k]['n_weighted'] * fr[k]['support'] for k in ('dem', 'con', 'independent'))
        rc = tot['n_weighted'] * tot['check'] - sum(fr[k]['n_weighted'] * fr[k]['check'] for k in ('dem', 'con', 'independent'))
        fr['residual_other_parties'] = {'n_weighted': resid_n, 'support': max(rs, 0) / resid_n, 'check': max(rc, 0) / resid_n,
                                        'derived': 'total minus listed rows (rounding error included)'}
        res['waves'][w] = {'pdf': pdf, 'pdf_sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'fieldwork_end': end,
                           'governing_party': governing, 'conservative_party_label': con,
                           'frame_by_party': fr, 'turnout_intention': turnout_rows(lines, con) or None}
    out = HP / 'frame_party_crosstabs.json'
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for w, v in res['waves'].items():
        f = v['frame_by_party']
        print(w, {k: (x['n_weighted'], round(x['support'], 3), round(x['check'], 3)) for k, x in f.items()}, v['turnout_intention'])


if __name__ == '__main__':
    main()
