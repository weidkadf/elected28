#!/usr/bin/env python3
"""NESDC national party-support table -> 조국혁신당 share of the Dem bloc, for the PR-seat sensitivity.

Input : data/nesdc/nesdc_major_data_national.xlsx  (NESDC '전국단위 선거여론조사결과 주요 데이터(2023.10.30.~)', board B0000025)
Output: data/nesdc/party_support_national.csv      (one row per registered poll, all sheets)
        outputs/jk_support.json                     (pre-2024 calibration, current window, monthly series, PR split scenarios)

Use (user decision 2026-11-11): party support is used only to set the 민주:조국혁신당 split of the Dem-bloc PR vote.
The bloc-vs-국민의힘 PR share still moves with the frame model. 여론조사꽃 is excluded (v0.5.0 rule).
Stdlib only.
"""
import csv, io, json, math, re, sys, zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / 'data/nesdc/nesdc_major_data_national.xlsx'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
PARTIES = ['더불어민주당', '국민의힘', '조국혁신당', '개혁신당', '진보당', '정의당', '새로운미래', '자유통일당', '기타정당', '지지정당 없음', '모름/ 무응답']
EXCLUDE = re.compile(r'여론조사꽃')
PR2024_RATIO = 24.25 / (26.69 + 24.25)          # NEC 2024 list vote: 조국혁신당 / (민주연합 + 조국혁신당)
PRE2024 = ('2024-03-25', '2024-04-03')           # last fieldwork days before the 2024-04-04 publication blackout
CURRENT_WINDOW_DAYS = 28
SINCE = '2026-06-04'                             # day after the 2026 local election


def logit(p): return math.log(p / (1 - p))
def inv(z): return 1 / (1 + math.exp(-z))


def read_sheets(path):
    z = zipfile.ZipFile(path)
    ss = [''.join(t.text or '' for t in si.iter('{%s}t' % NS['m'])) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    target = {r.get('Id'): r.get('Target') for r in rels}
    for sh in wb.find('m:sheets', NS):
        rid = sh.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        x = ET.fromstring(z.read('xl/' + target[rid].lstrip('/').removeprefix('xl/')))
        rows = []
        for r in x.iter('{%s}row' % NS['m']):
            row = {}
            for c in r.findall('m:c', NS):
                col = 0
                for ch in re.match(r'[A-Z]+', c.get('r')).group(): col = col * 26 + ord(ch) - 64
                v = c.find('m:v', NS); t = c.get('t')
                if v is not None: val = ss[int(v.text)] if t == 's' else v.text
                else: val = ''.join(e.text or '' for e in c.iter('{%s}t' % NS['m']))
                row[col - 1] = re.sub(r'\s+', ' ', val or '').strip()
            rows.append([row.get(i, '') for i in range(max(row) + 1)] if row else [])
        yield sh.get('name'), rows


def parse_dates(s):
    parts = [[int(n) for n in p.split('.') if n] for p in re.split(r'[~/]|,(?=\d)', re.sub(r'\s', '', s))]
    a, b = parts[0], parts[-1]
    if len(a) != 3 or not 1 <= len(b) <= 3: raise ValueError(s)
    start = date(2000 + a[0], a[1], a[2])
    if len(parts) == 1: return start, start
    e = b if len(b) == 3 else [a[0]] + b if len(b) == 2 else [a[0], a[1], b[0]]
    if len(b) < 3 and e[1] < a[1]: e[0] = a[0] + 1
    end = date(2000 + e[0], e[1], e[2])
    if not 0 <= (end - start).days <= 20: raise ValueError(s)
    return start, end


def mode(method):
    cati, ars = '면접' in method, 'ARS' in method
    return 'mixed' if cati and ars else 'CATI' if cati else 'ARS'


def build_rows():
    out = []
    for sheet, rows in read_sheets(XLSX):
        hdr = None
        for c in rows:
            if len(c) > 10 and c[10] == '더불어민주당': hdr = c; continue
            if not c or not c[0].isdigit() or hdr is None: continue
            s, e = parse_dates(c[3])
            rec = {'reg_no': int(c[0]), 'pollster': c[1], 'sponsor': c[2], 'fieldwork_start': s.isoformat(), 'fieldwork_end': e.isoformat(),
                   'method': c[4], 'mode': mode(c[4]), 'frame': c[5], 'n': c[6], 'sheet': sheet}
            for p in PARTIES:
                v = c[hdr.index(p)] if p in hdr and hdr.index(p) < len(c) else ''
                rec[p] = '' if v in ('', '-') else round(float(v), 2)
            out.append(rec)
    # sheets overlap at their date boundaries; the same registration can appear twice. Main parties must agree; keep the later sheet.
    by = {}
    for r in out:
        if r['reg_no'] in by:
            prev = by[r['reg_no']]
            assert all(prev[p] == r[p] for p in ('더불어민주당', '국민의힘', '조국혁신당')), r['reg_no']
        by[r['reg_no']] = r
    out = sorted(by.values(), key=lambda r: (r['fieldwork_end'], r['reg_no']))
    return out


def pooled(polls, qw):
    """Mean logit ratio: within-pollster mean, then quality-weighted across pollsters (weight = mean mode weight)."""
    by = {}
    for p in polls: by.setdefault(p['pollster'], []).append(p)
    z = w = 0.0
    for ps in by.values():
        wi = sum(qw[p['mode']] for p in ps) / len(ps)
        z += wi * sum(logit(p['ratio']) for p in ps) / len(ps); w += wi
    return {'ratio': round(inv(z / w), 4), 'logit': round(z / w, 4), 'n_polls': len(polls), 'n_pollsters': len(by),
            'jk_mean_pct': round(sum(p['조국혁신당'] for p in polls) / len(polls), 2)}


NAMED = ['더불어민주당', '국민의힘', '조국혁신당', '개혁신당', '진보당', '정의당', '새로운미래', '자유통일당', '기타정당']
REF2024_LIST = 3.61                              # NEC 2024 list vote %, 개혁신당


def reform(rows, qw, pre_w, cur_w):
    """개혁신당 share of respondents naming a party (≈ share of valid list votes). Same pooling and scenarios as the 조국 ratio."""
    use = []
    for r in rows:
        if EXCLUDE.search(r['pollster']) or r['개혁신당'] in ('', 0): continue
        named = sum(r[p] for p in NAMED if r[p] != '')
        use.append(dict(r, ratio=r['개혁신당'] / named, jk_mean_pct=0))
    pre = [p for p in use if pre_w[0] <= p['fieldwork_end'] <= pre_w[1]]
    cur = [p for p in use if cur_w[0] < p['fieldwork_end'] <= cur_w[1]]
    def pool(ps):
        d = pooled([dict(p, 조국혁신당=p['개혁신당']) for p in ps], qw); d['ref_mean_pct'] = d.pop('jk_mean_pct'); return d
    out = {'definition': 'share = 개혁신당 / sum of named parties (excl. no party, don\'t know); pooled like the 조국 ratio',
           'pr2024_list_share_pct': REF2024_LIST, 'pre2024': {'all': pool(pre)}, 'current': {'all': pool(cur)}}
    sw = {}
    for m in ('ARS', 'CATI'):
        out['pre2024'][m] = pool([p for p in pre if p['mode'] == m]); out['current'][m] = pool([p for p in cur if p['mode'] == m])
        sw[m] = out['current'][m]['logit'] - out['pre2024'][m]['logit']
    s = (qw['ARS'] * sw['ARS'] + qw['CATI'] * sw['CATI']) / (qw['ARS'] + qw['CATI'])
    base = logit(REF2024_LIST / 100)
    out['swing_logit_by_mode'] = {k: round(v, 4) for k, v in sw.items()}; out['swing_logit'] = round(s, 4)
    out['scenarios'] = {'fixed_2024': {'share_pct': REF2024_LIST, 'label': '2024 득표 고정'},
                        'poll_swing': {'share_pct': round(100 * inv(base + s), 2), 'label': '여론 변화 반영',
                                       **{f'share_pct_{m}_only': round(100 * inv(base + sw[m]), 2) for m in sw}},
                        'poll_direct': {'share_pct': round(100 * out['current']['all']['ratio'], 2), 'label': '현재 지지율 그대로'}}
    month = {}
    for p in use:
        if p['fieldwork_end'] >= SINCE: month.setdefault(p['fieldwork_end'][:7], []).append(p)
    out['monthly_since_2026_local'] = {k: pool(v) for k, v in sorted(month.items())}
    return out


def main():
    cfg = json.loads((ROOT / 'config/forecast_v050.json').read_text(encoding='utf-8'))
    q = cfg['frame_inputs']['aggregator']['quality_weights']
    qw = {'ARS': q['ARS_RDD'], 'CATI': q['CATI_live_interview'], 'mixed': (q['ARS_RDD'] + q['CATI_live_interview']) / 2}
    rows = build_rows()
    with (ROOT / 'data/nesdc/party_support_national.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n'); w.writeheader(); w.writerows(rows)

    use = [dict(r, ratio=r['조국혁신당'] / (r['조국혁신당'] + r['더불어민주당'])) for r in rows
           if r['조국혁신당'] != '' and r['더불어민주당'] != '' and r['조국혁신당'] > 0 and not EXCLUDE.search(r['pollster'])]
    # the window follows new data: it ends at the later of the model as_of and the newest poll in the workbook
    as_of = max(date.fromisoformat(cfg['as_of']), date.fromisoformat(rows[-1]['fieldwork_end']))
    lo = (as_of - timedelta(days=CURRENT_WINDOW_DAYS)).isoformat()
    pre = [p for p in use if PRE2024[0] <= p['fieldwork_end'] <= PRE2024[1]]
    cur = [p for p in use if lo < p['fieldwork_end'] <= as_of.isoformat()]

    res = {'source': {'file': str(XLSX.relative_to(ROOT)).replace('\\', '/'), 'board': 'https://www.nesdc.go.kr/portal/bbs/B0000025/list.do?menuNo=200500',
                      'n_rows': len(rows), 'first_fieldwork_end': rows[0]['fieldwork_end'], 'last_fieldwork_end': rows[-1]['fieldwork_end'],
                      'excluded_pollsters': '여론조사꽃'},
           'definition': 'ratio = 조국혁신당 / (더불어민주당 + 조국혁신당) in national party support; pooled in logit, within pollster then quality-weighted',
           'quality_weights': qw, 'pr2024_list_ratio': round(PR2024_RATIO, 4),
           'pre2024': {'window': PRE2024, 'all': pooled(pre, qw)},
           'current': {'window': [lo, as_of.isoformat()], 'all': pooled(cur, qw)}}
    swings = {}
    for m in ('ARS', 'CATI'):
        a, b = [p for p in pre if p['mode'] == m], [p for p in cur if p['mode'] == m]
        res['pre2024'][m], res['current'][m] = pooled(a, qw), pooled(b, qw)
        swings[m] = res['current'][m]['logit'] - res['pre2024'][m]['logit']
    sw = (qw['ARS'] * swings['ARS'] + qw['CATI'] * swings['CATI']) / (qw['ARS'] + qw['CATI'])
    res['list_vote_uplift_logit'] = round(logit(PR2024_RATIO) - res['pre2024']['all']['logit'], 4)
    res['swing_logit_by_mode'] = {k: round(v, 4) for k, v in swings.items()}
    res['swing_logit'] = round(sw, 4)
    sc = {'fixed_2024': {'ratio': round(PR2024_RATIO, 4), 'label': '2024 비례 득표비 고정', 'basis': 'NEC 2024 list vote'},
          'poll_swing': {'ratio': round(inv(logit(PR2024_RATIO) + sw), 4), 'label': '여론 변화 반영',
                         'basis': '2024 list ratio moved by the within-mode change in poll ratio, pre-2024 window -> current window'},
          'poll_direct': {'ratio': res['current']['all']['ratio'], 'label': '현재 지지율 그대로',
                          'basis': 'current pooled poll ratio; no list-vote uplift (2024 polls understated 조국혁신당 list vote)'}}
    for m in ('ARS', 'CATI'):
        sc['poll_swing'][f'ratio_{m}_only'] = round(inv(logit(PR2024_RATIO) + swings[m]), 4)
    res['scenarios'] = sc
    month = {}
    for p in use:
        if p['fieldwork_end'] >= SINCE: month.setdefault(p['fieldwork_end'][:7], []).append(p)
    res['monthly_since_2026_local'] = {k: pooled(v, qw) for k, v in sorted(month.items())}
    res['reform'] = reform(rows, qw, pre_w=PRE2024, cur_w=(lo, as_of.isoformat()))
    (ROOT / 'outputs/jk_support.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: res[k] for k in ('pre2024', 'current', 'swing_logit', 'list_vote_uplift_logit')}, ensure_ascii=False))
    print({k: v['ratio'] for k, v in sc.items()}, sc['poll_swing'])


if __name__ == '__main__':
    main()
