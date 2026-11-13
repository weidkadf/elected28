#!/usr/bin/env python3
"""Find 정부지원·견제 / 정권심판 frame questions in newly registered national NESDC polls (board B0000005).

Semi-automatic: this only builds a review list. Nothing here is written to data/frame_polls_multi.json, because
UPDATE_PROTOCOL requires the exact wording, role direction, wording class and publication date to be checked by hand.

Per new national registration (여론조사꽃 excluded):
  1. read the questionnaire PDF (public on registration) and look for a question whose options pit
     government support/stability against check/judgment;
  2. once the result PDF opens (24-48 h after first publication), find the matching table and make a best-effort
     read of the national row and the region rows, keeping the raw table text for review.

State: data/nesdc/frame_scan_state.json. Review list: outputs/frame_candidates.json.
Exit code 0 = a candidate was added or got new results (--summary then holds an issue body), 3 = nothing new for review,
anything else = failure. The files carry no run timestamp, so a run that finds nothing leaves no diff.
Needs pdfplumber (pdftotext builds without poppler-data drop Korean glyphs in these PDFs).
"""
import argparse, html, io, json, re, sys, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from parse_nesdc_frames import region_of  # noqa: E402  (same region labels as the 2024 archive)

BASE = 'https://www.nesdc.go.kr'
LIST = BASE + '/portal/bbs/B0000005/list.do?menuNo=200467&searchCnd=4&searchWrd=' + urllib.parse.quote('전국') + '&pageIndex={}'
VIEW = BASE + '/portal/bbs/B0000005/view.do?nttId={}&menuNo=200467'
STATE = ROOT / 'data/nesdc/frame_scan_state.json'
OUT = ROOT / 'outputs/frame_candidates.json'
REGISTRIES = (ROOT / 'data/frame_polls_multi.json', ROOT / 'data/frame_polls_v050.json')
UA = {'User-Agent': 'Mozilla/5.0 (compatible; election-model-updater)'}
EXCLUDED = ('여론조사꽃',)
FIRST_SINCE = '2026-10-01'      # first run looks back to here
RESULT_WAIT_DAYS = 14           # stop re-checking for a result PDF after this many days

SUP = re.compile(r'지원|안정|힘을?\s*실어|뒷받침|재창출')
CHK = re.compile(r'견제|심판|교체')
OPP_TARGET = re.compile(r'야당\S{0,3}\s*(심판|견제)')   # "야당을 심판" points the other way
QMARK = re.compile(r'^\s*(\[|Q\s*\d|문\s*\d|SQ\s*\d|0\d\.|\d{1,2}\.\s.*\?\s*$)')
OPT = re.compile(r'^\s*(?:[①-⑨]|\d\)|\(\d\)|\d\.(?=\s))\s*(?:번\s*[,.]?)?\s*(.+?)\s*$')
ARS_TAIL = re.compile(r'\s*(?:이)?면\s*\d+\)\s*번.*$')   # '...한다면 1)번을, 눌러주세요'
NUMTOK = re.compile(r'(?<![\w.])\(?-?\d[\d,]*\.?\d*\)?%?(?![\w])|(?<![\w\d])\.\d+')


def get(url, referer=None):
    h = dict(UA, **({'Referer': referer} if referer else {}))
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return r.read()
        except OSError:
            if i == 2: raise
            time.sleep(5)


def flat(page):
    t = re.sub(r'<script.*?</script>', '', page, flags=re.S)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', t)))


def list_page(i):
    t = get(LIST.format(i)).decode('utf-8', 'replace')
    rows = []
    for m in re.finditer(r'nttId=(\d+)[^"]*"\s*class="row tr">(.*?)</a>', t, re.S):
        c = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', x)).strip() for x in re.findall(r'</i>(.*?)</span>', m.group(2), re.S)]
        if len(c) >= 8:
            rows.append({'ntt': int(m.group(1)), 'reg_no': int(c[0]), 'pollster': c[1], 'sponsor': c[2], 'mode': c[3],
                         'frame': c[4], 'title': c[5], 'registered': c[6], 'area': c[7]})
    return rows


def view_info(ntt):
    page = get(VIEW.format(ntt), BASE).decode('utf-8', 'replace')
    txt = flat(page)
    files = []
    for m in re.finditer(r"view\('([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)'\);\"\s*>\s*([^<]*?)\s*</a>", page):
        files.append({'name': m.group(5).strip(),
                      'url': BASE + '/portal/cmm/fms/FileDown.do?atchFileId={}&fileSn={}&bbsId={}&bbsKey={}'.format(*m.groups()[:4])})
    m = re.search(r'조사일시(.*?)조사일수', txt)
    days = re.findall(r'\d{4}-\d\d-\d\d', m.group(1)) if m else []
    pub = re.search(r'최초 공표\S*\s*(?:보도\s*)?(?:지정|예정)일시\s*\(?\s*(\d{4}-\d\d-\d\d)(?:\s*(\d\d)시\s*(\d\d)분)?', txt)
    n = re.search(r'조사완료 사례수\(명\) 가중값 적용 기준 사례수\(명\) 전체 (\d+) (\d+)', txt)
    rr = re.search(r'응답률 \(I/\(I\+R\)\) (\d+\.?\d*)%', txt)
    q = [f for f in files if re.search(r'질문|설문', f['name'])]
    res = [f for f in files if f not in q]
    if not q:   # unnamed single questionnaire before the results open
        q = [f for f in res if not re.search(r'결과|통계|집계|보고|분석|교차|table', f['name'], re.I)]
        res = [f for f in res if f not in q]
    return {'fieldwork_start': min(days) if days else None, 'fieldwork_end': max(days) if days else None,
            'published_at': (pub.group(1) + (f' {pub.group(2)}:{pub.group(3)}' if pub.group(2) else '')) if pub else None,
            'sample_size': int(n.group(1)) if n else None, 'response_rate_pct': float(rr.group(1)) if rr else None,
            'questionnaire': q, 'results': res}


def pdf_text(blob, layout, columns=False):
    """Text of every page; columns=True reads the left and right halves separately (two-column questionnaires)."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        if not columns:
            return '\f'.join((p.extract_text(layout=layout) or '') for p in pdf.pages)
        return '\f'.join((p.crop((x0, 0, x1, p.height)).extract_text(layout=layout) or '')
                         for p in pdf.pages for x0, x1 in ((0, p.width / 2), (p.width / 2, p.width)))


def role(opt):
    if OPP_TARGET.search(opt): return 'support?'
    s, c = bool(SUP.search(opt)), bool(CHK.search(opt))
    return 'support' if s and not c else 'check' if c and not s else 'other'


def find_question(text):
    """Return (question text, options) for the first block whose options contrast support with check, else None."""
    text = re.sub(r'[-]', '', text)   # private-use glyphs (box drawing in some fonts)
    lines = [l.strip() for l in text.replace('\f', '\n').split('\n') if l.strip()]
    starts = [i for i, l in enumerate(lines) if QMARK.match(l)] + [len(lines)]
    for a, b in zip(starts, starts[1:]):
        block = lines[a:b]
        joined = ' '.join(block)
        if not CHK.search(joined) or not re.search(r'국회의원|총선|선거', joined): continue
        opts = []
        for l in block[1:]:
            if OPT.match(l): opts.append(OPT.match(l).group(1))
            elif opts and not re.match(r'[(\[※*]', l) and len(opts[-1]) < 60: opts[-1] += ' ' + l   # wrapped option text
        opts = [ARS_TAIL.sub('', o).strip(' ,.') for o in opts]
        roles = [role(o) for o in opts]
        if any(r.startswith('support') for r in roles) and 'check' in roles:
            first_opt = next(j for j, l in enumerate(block) if j and OPT.match(l))
            q = ' '.join(l for l in block[:first_opt] if not l.startswith(('호명', '(☞')))
            return re.sub(r'\s+', ' ', q)[:400], opts
    return None


def numbers(s):
    out = []
    for tok in NUMTOK.findall(s):
        raw = tok.strip('()%')
        try: out.append((float(raw.replace(',', '')), '.' in raw and ',' not in raw))
        except ValueError: pass
    return out


def split_row(line, k):
    """Label, the k option shares (a window summing to ~100; trailing net columns ignored) and the sample counts just before it."""
    m = NUMTOK.search(line)
    if not m: return None
    nums = numbers(line[m.start():])
    for off in range(len(nums) - k + 1):
        w = [v for v, _ in nums[off:off + k]]
        if 97 <= sum(w) <= 103 and all(0 <= v <= 100 for v in w):
            cnt = [v for v, dec in nums[max(0, off - 2):off] if not dec and v >= 10]
            return line[:m.start()].strip(), w, cnt
    return None


def read_table(text, opts):
    """Best-effort read of the frame table: national shares, region shares and the raw page text."""
    k = len(opts)
    for pi, page in enumerate(text.split('\f')):
        lines = [l.rstrip() for l in page.split('\n') if l.strip()]
        first = next((i for i, l in enumerate(lines) if split_row(l, k)), len(lines))
        head = re.sub(r'\s', '', ' '.join(lines[:first]))   # title and column header of the page's first table
        if not (CHK.search(head) and (SUP.search(head) or '프레임' in head)): continue
        rows = [(i, split_row(l, k)) for i, l in enumerate(lines)]
        rows = [(i, r) for i, r in rows if r]
        if not rows: continue
        nat = next((r for _, r in rows if re.sub(r'\s', '', r[0]) in ('전체', '합계', '전국', 'Total')), None)
        if nat is None:   # trend tables (리서치뷰): the latest wave is the row before the first sex row
            sex = next((j for j, (_, r) in enumerate(rows) if re.search(r'남성|남자|^남$', re.sub(r'\s', '', r[0]).split('별')[-1])), None)
            nat = rows[sex - 1][1] if sex else None
        if nat is None: continue
        reg = {}
        for _, (lab, w, cnt) in rows:
            r = region_of(lab.split()[-1].replace('전남광주', '광주/전남')) if lab.split() else None
            if r and r not in reg: reg[r] = {'shares': w, 'n': cnt[-1] if cnt and cnt[-1] >= 10 else None}
        return {'page': pi + 1, 'national_label': nat[0], 'national': dict(zip(opts, nat[1])),
                'national_n': nat[2][-1] if nat[2] and nat[2][-1] >= 100 else None,
                'regions': reg, 'raw_text': '\n'.join(lines[:90])}
    return None


def is_total(t):
    return bool(t) and re.sub(r'\s', '', t['national_label']) in ('전체', '합계', '전국', 'Total')


def read_result_pdf(blob, opts):
    """Whole pages first; if that gives no '전체' row, retry on the left half (Gallup prints a trend chart on the right)."""
    t = read_table(pdf_text(blob, layout=True), opts)
    if is_total(t): return t
    left = read_table('\f'.join(pdf_text(blob, layout=True, columns=True).split('\f')[0::2]), opts)
    if left: left['page'] = f"{left['page']} (left half)"
    return left if is_total(left) or not t else t


def pkey(pollster, end):
    return re.sub(r'\(주\)|㈜|주식회사|\s', '', pollster or '')[:4], end


def registered_keys():
    """(pollster prefix, fieldwork_end) and NESDC reg numbers already in a frame registry, mapped to the file name."""
    keys = {}
    for path in REGISTRIES:
        try: polls = json.loads(path.read_text(encoding='utf-8'))['polls']
        except (OSError, KeyError, ValueError): continue
        for p in polls:
            for k in (pkey(p.get('pollster'), p.get('fieldwork_end')), str(p.get('nesdc_reg_no') or '')):
                if k and k != '': keys.setdefault(k, path.name)
    return keys


def process(rec, today):
    """Update one candidate in place. Returns True when something reviewable changed."""
    info = view_info(rec['ntt'])
    rec.update({k: v for k, v in info.items() if k not in ('questionnaire', 'results')})
    changed = False
    if rec['status'] == 'new':
        if not info['questionnaire']:
            if (today - date.fromisoformat(rec['registered'])).days > RESULT_WAIT_DAYS: rec['status'] = 'no_questionnaire'
            return False
        q = None
        for f in info['questionnaire']:
            blob = get(f['url'], VIEW.format(rec['ntt']))
            q = find_question(pdf_text(blob, layout=False)) or find_question(pdf_text(blob, layout=False, columns=True))
            if q: break
        if not q:
            rec['status'] = 'no_frame_question'; return False
        rec['question'], rec['options'] = q
        rec['option_roles'] = [role(o) for o in q[1]]
        rec['status'] = 'awaiting_results'; changed = True
    if rec['status'] == 'awaiting_results':
        if info['results']:
            for f in info['results']:
                t = read_result_pdf(get(f['url'], VIEW.format(rec['ntt'])), rec['options'])
                if t:
                    rec.update(result_file=f['name'], table=t, status='parsed'); break
            else:
                rec['status'] = 'results_unparsed'
            return True
        if (today - date.fromisoformat(rec['registered'])).days > RESULT_WAIT_DAYS:
            rec['status'] = 'results_not_published'
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-pages', type=int, default=10)
    ap.add_argument('--today', default=None)
    ap.add_argument('--summary', type=Path, default=None, help='write a Markdown issue body for candidates changed in this run')
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone(timedelta(hours=9))).date()
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'last_reg_no': 0, 'since': FIRST_SINCE, 'polls': {}}
    polls = state['polls']
    new = []
    for i in range(1, a.max_pages + 1):
        rows = list_page(i)
        fresh = [r for r in rows if r['reg_no'] > state['last_reg_no'] and r['registered'] >= state['since']]
        new += [r for r in fresh if str(r['reg_no']) not in polls]
        if len(fresh) < len(rows) or not rows: break
        time.sleep(1)
    for r in new:
        polls[str(r['reg_no'])] = dict(r, status='excluded_pollster' if any(x in r['pollster'] for x in EXCLUDED) else 'new')
    touched = []
    for key, rec in sorted(polls.items(), key=lambda kv: int(kv[0])):
        if rec['status'] in ('new', 'awaiting_results'):
            try:
                if process(rec, today): touched.append(key)
                rec.pop('last_error', None)
            except Exception as e:  # one broken PDF must not stop the scan; retry on later runs, then give up
                rec['last_error'] = f'{type(e).__name__}: {e}'[:300]
                print('error', key, rec['last_error'], file=sys.stderr)
                if (today - date.fromisoformat(rec['registered'])).days > RESULT_WAIT_DAYS: rec['status'] = 'error'
            time.sleep(1)
    changed = bool(touched)
    if polls: state['last_reg_no'] = max(state['last_reg_no'], max(int(k) for k in polls))
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    reg = registered_keys()
    cands = []
    for key, rec in sorted(polls.items(), key=lambda kv: -int(kv[0])):
        if 'question' not in rec: continue
        c = {k: rec.get(k) for k in ('reg_no', 'pollster', 'sponsor', 'mode', 'fieldwork_start', 'fieldwork_end', 'published_at', 'registered',
                                     'sample_size', 'response_rate_pct', 'status', 'question', 'options', 'option_roles', 'result_file', 'table')}
        c['nesdc_url'] = VIEW.format(rec['ntt'])
        c['registered_in'] = reg.get(key) or reg.get(pkey(rec['pollster'], rec.get('fieldwork_end')))
        cands.append(c)
    OUT.write_text(json.dumps({'note': '검토 전 후보 목록이다. 계산 입력이 아니며 data/frame_polls_multi.json 등록은 원문 확인 후 수동으로 한다.',
                               'candidates': cands}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    todo = [c for c in cands if c['registered_in'] != 'frame_polls_multi.json' and c['status'] in ('parsed', 'results_unparsed')]
    print(f"new registrations {len(new)}, candidates {len(cands)}, awaiting review {len(todo)}, changed {changed}")
    if a.summary and touched:
        a.summary.write_text(summary_md([c for c in cands if str(c['reg_no']) in touched]), encoding='utf-8')
    sys.exit(0 if changed else 3)


def summary_md(cs):
    """Issue body for the candidates this run added or completed."""
    out = ['여심위 등록 전국 조사에서 정부지원·견제/심판 문항 후보를 찾았다. 아직 계산 입력이 아니다.',
           '원문(질문지·결과표)과 대조한 뒤 `data/frame_polls_multi.json`에 등록한다(UPDATE_PROTOCOL: 문항 등급 A/B, 검증 수준, 공표일 필수).', '']
    for c in cs:
        t = c.get('table') or {}
        out += [f"### 등록번호 {c['reg_no']} · {c['pollster']} ({c['sponsor']})",
                f"- 조사 {c['fieldwork_start']}~{c['fieldwork_end']}, 공표 {c['published_at']}, 표본 {c['sample_size']}, {c['mode']}",
                f"- 상태: `{c['status']}`" + (f", 이미 `{c['registered_in']}`에 있음" if c['registered_in'] else ''),
                f"- 문항: {c['question']}"]
        for o, r in zip(c['options'], c['option_roles']):
            v = (t.get('national') or {}).get(o)
            out.append(f"  - [{r}] {o}" + (f" — **{v}%**" if v is not None else ''))
        if t: out.append(f"- 결과표 {c['result_file']} p.{t['page']}, 권역 {len(t.get('regions', {}))}곳 자동 판독")
        out += [f"- 원문: {c['nesdc_url']}", '']
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    main()
