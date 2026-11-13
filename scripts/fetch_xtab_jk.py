#!/usr/bin/env python3
"""조국혁신당 column for the frame x party crosstabs used by identify_alpha (micro route).

frame_tables.json keeps only the 민주 and 국민의힘 columns. For every crosstab whose header names 조국혁신당 this
re-downloads the NESDC result PDFs, finds the table rows by word position (pdfplumber), and records the 조국혁신당
value of the total row and the two frame rows. A value is kept only when the 민주 and 국민의힘 values read from
the same line equal the stored ones (after identify_alpha.fix_party_order), so a wrong column is not picked up.
Output: data/nesdc/frame_xtab_jk.json. PDFs are cached in .cache/nesdc_pdf/ (not committed).
"""
import csv, io, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pdfplumber  # noqa: E402
import identify_alpha as I  # noqa: E402
import scan_nesdc_frame_candidates as S  # noqa: E402
CACHE = ROOT / '.cache/nesdc_pdf'
OUT = ROOT / 'data/nesdc/frame_xtab_jk.json'
ANCHORS = {'D': re.compile(r'^더불어'), 'C': re.compile(r'^국민의'), 'J': re.compile(r'^조국')}
NUMW = re.compile(r'^\(?-?\d[\d,]*\.?\d*\)?%?$')


def pdfs(reg, ntt):
    d = CACHE / reg; d.mkdir(parents=True, exist_ok=True)
    have = sorted(d.glob('*.pdf'))
    if have: return have
    info = S.view_info(ntt)
    for i, f in enumerate(info['results'] + info['questionnaire'], 1):
        blob = S.get(f['url'], S.VIEW.format(ntt))
        if blob[:4] == b'%PDF': (d / f'{i}.pdf').write_bytes(blob)
    return sorted(d.glob('*.pdf'))


def lines_of(words):
    rows = []
    for w in sorted(words, key=lambda w: (round(w['top']), w['x0'])):
        if rows and abs(rows[-1][0] - w['top']) < 3: rows[-1][1].append(w)
        else: rows.append([w['top'], [w]])
    return rows


def num(t):
    try: return float(t.strip('()%').replace(',', ''))
    except ValueError: return None


def read_page(page, targets):
    """targets: {'tot': (D, C), 's': (D, C), 'c': (D, C)} -> {'tot': J, ...} for lines whose D and C match."""
    words = page.extract_words()
    found = {}
    lines = lines_of(words)
    for li, (top, ws) in enumerate(lines):
        if not any(ANCHORS['D'].search(w['text']) for w in ws): continue
        anc = {}
        for _, ws1 in lines[max(0, li - 3):li + 4]:      # multi-line headers: party names sit on different lines
            for k, pat in ANCHORS.items():
                hit = [w for w in ws1 if pat.search(w['text'])]
                if hit and k not in anc: anc[k] = (hit[0]['x0'] + hit[0]['x1']) / 2
        if len(anc) < 3: continue
        # header found: column centre of each party from the header block (word on this line or the line below)
        xs = sorted(anc.values()); tol = min(b - a for a, b in zip(xs, xs[1:])) / 2
        for top2, ws2 in lines[li + 1:li + 80]:
            nums = [(num(w['text']), (w['x0'] + w['x1']) / 2) for w in ws2 if NUMW.match(w['text'])]
            nums = [(v, x) for v, x in nums if v is not None]
            if len(nums) < 3: continue
            got = {}
            for k, ax in anc.items():
                near = [v for v, x in nums if abs(x - ax) <= tol]
                if len(near) == 1: got[k] = near[0]
            if len(got) < 3: continue
            for key, (d, c) in targets.items():
                if key not in found and abs(got['D'] - d) < 0.051 and abs(got['C'] - c) < 0.051:
                    found[key] = got['J']
        if len(found) == len(targets): return found
    return found if len(found) == len(targets) else None


def read_page_text(page, targets):
    """Fallback for run-together headers ('더불어국민의조국혁…') where word positions cannot separate the columns: only when
    the header lists 더불어 -> 국민의 -> 조국 with no other party between, 조국 is the third share on a line whose first two
    shares equal the stored 민주/국민의힘 values."""
    import parse_nesdc_frames as PF
    lines = page.extract_text(layout=True).split('\n')
    found = {}
    for i, l in enumerate(lines):
        if '더불어' not in l: continue
        h = re.sub(r'\s', '', ' '.join(lines[max(0, i - 3):i + 4]))
        m = re.search(r'더불어.*?국민의(.*?)조국', h)
        if not m or re.search(r'민주당.*민주당|녹색|정의|새로운|개혁|진보|기본|사회', m.group(1)): continue
        for l2 in lines[i + 1:i + 80]:
            _, v = PF.vals(l2)
            if len(v) < 3: continue
            for key, (d, c) in targets.items():
                if key not in found and abs(v[0] - d) < 0.051 and abs(v[1] - c) < 0.051: found[key] = v[2]
        if len(found) == len(targets): return found
    return None


def main():
    idx = {r['등록번호']: r for r in csv.DictReader(open(ROOT / 'data/nesdc/nesdc_polls_index.csv', encoding='utf-8-sig'))}
    polls = json.loads((ROOT / 'data/nesdc/frame_tables.json').read_text(encoding='utf-8'))
    I.fix_party_order(polls)
    out, miss = {}, []
    for o in polls:
        tabs = [t for t in o['xtabs'] if '조국' in re.sub(r'\s', '', t['title'])]
        if not tabs: continue
        ntt = int(re.search(r'nttId=(\d+)', idx[o['reg']]['상세주소']).group(1))
        files = pdfs(o['reg'], ntt)
        docs = [pdfplumber.open(f) for f in files]
        for t in tabs:
            targets = {'tot': (t['tot']['D'], t['tot']['C'])}
            targets.update({k: (r['D'], r['C']) for k, r in t['rows'].items()})
            res = None
            for doc in docs:
                pg = [t['page'] - 1] + [i for i in range(len(doc.pages)) if i != t['page'] - 1]
                for i in pg:
                    try: res = read_page(doc.pages[i], targets) or read_page_text(doc.pages[i], targets)
                    except Exception: res = None
                    if res: break
                if res: break
            key = f"{o['reg']}:{t['page']}:{t['tot']['D']}:{t['tot']['C']}"
            if res: out[key] = {'reg': o['reg'], 'page': t['page'], 'J': res}
            else: miss.append(key)
        for d in docs: d.close()
        print(o['reg'], len(tabs), 'tables', sum(1 for k in out if k.startswith(o['reg'] + ':')), 'read', flush=True)
    OUT.write_text(json.dumps({'schema_version': 'frame_xtab_jk_1', 'definition': '조국혁신당 % in the total row and the frame rows of crosstabs in frame_tables.json; '
                               'kept only when 민주/국민의힘 on the same line match the stored values', 'tables': out, 'unread': miss},
                              ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('read', len(out), 'unread', len(miss))


if __name__ == '__main__':
    main()
