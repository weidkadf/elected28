import csv, re, json, sys
NAMES = ['이재명', '김문수', '이준석']
TOT = re.compile(r'^\s*[■▣◆●▶\[\(\|]*\s*(전\s*체|합\s*계|전\s*국|계|TOTAL|Total|total)\b')
NUM = re.compile(r'\(?-?\d[\d,]*\.?\d*\)?%?')
GOOD = ['투표하', '투표할', '지지하', '지지할', '누구에게', '누구를', '뽑', '지지도', '후보 지지', '대선후보지지', '찍']
BAD = ['당선', '가능성', '호감', '토론', '절대', '단일화', '가상', '양자', '적합', '이미지', '신뢰', '도덕', '능력', '실수', '잘한', '잘했', '못한', '비호감', '사퇴', '승리', '이길', '될것', '될 것', '2위', '교체', '싫', '바뀔', '계속', '지난', '20대', '2022', '투표한', '인상']
def tables_x(text):
    out = []
    for pi, page in enumerate(text.split('\f')):
        lines = page.split('\n')
        i = 0
        while i < len(lines):
            pos = {}
            for k in range(i, min(i + 5, len(lines))):
                for nm in NAMES:
                    if nm in pos: continue
                    m = re.search(r'\s?'.join(nm), lines[k])
                    if m: pos[nm] = ((m.start() + m.end()) / 2, k)
                if len(pos) == 3: break
            if len(pos) < 3 or min(abs(pos[a][0] - pos[b][0]) for a in NAMES for b in NAMES if a < b) < 5:
                i += 1; continue
            hend = max(v[1] for v in pos.values())
            hit = None
            for j in range(hend + 1, min(hend + 12, len(lines))):
                if not TOT.search(lines[j]): continue
                cand_lines = [lines[j]] + ([lines[j + 1]] if j + 1 < len(lines) else [])
                for cl in cand_lines:
                    nums = [(m.start(), m.end(), m.group()) for m in NUM.finditer(cl)]
                    vals = {}
                    for nm in NAMES:
                        best = None
                        for s, e, g in nums:
                            if '(' in g: continue
                            d = abs((s + e) / 2 - pos[nm][0])
                            if best is None or d < best[0]: best = (d, g)
                        if best and best[0] <= 7:
                            try: vals[nm] = float(best[1].replace(',', '').replace('%', ''))
                            except ValueError: pass
                    if len(vals) == 3 and 60 <= sum(vals.values()) <= 100.5 and max(vals.values()) < 70 and min(vals.values()) > 0:
                        hit = vals; break
                break
            if hit:
                q = ' '.join(x.strip() for x in lines[max(0, i - 22):i] if len(re.findall('[가-힣]', x)) >= 6)[-400:]
                qq = q.replace(' ', '')
                sc = sum(g.replace(' ', '') in qq for g in GOOD) - 2 * sum(b in qq for b in BAD)
                out.append({'page': pi + 1, 'vals': hit, 'q': q, 'score': sc})
            i = hend + 1
    return out

ORD = re.compile(r'이\s?재\s?명[^\d\n]{0,80}?김\s?문\s?수[^\d\n]{0,80}?이\s?준\s?석')
def order_vals(line):
    toks = [m.group() for m in NUM.finditer(line)]
    vals = []
    started = False
    for g in toks:
        raw = g.replace('%', '')
        if not started and ('(' in raw or ',' in raw or (('.' not in raw) and float(raw.strip('()').replace(',', '') or 0) >= 150)):
            continue
        if '(' in raw: break
        started = True
        try: vals.append(float(raw.replace(',', '')))
        except ValueError: break
    return vals
def tables(text):
    out = []
    for pi, page in enumerate(text.split('\f')):
        lines = page.split('\n')
        for i, ln in enumerate(lines):
            if not ORD.search(ln): continue
            for j in range(i + 1, min(i + 9, len(lines))):
                if not TOT.search(lines[j]): continue
                v = order_vals(TOT.sub('', lines[j], 1))
                if len(v) >= 3 and 60 <= sum(v[:3]) <= 100.5 and min(v[:3]) > 0 and v[0] != 100:
                    q = ' '.join(x.strip() for x in lines[max(0, i - 22):i] if len(re.findall('[가-힣]', x)) >= 6)[-400:]
                    qq = q.replace(' ', '')
                    sc = sum(g.replace(' ', '') in qq for g in GOOD) - 2 * sum(b.replace(' ', '') in qq for b in BAD)
                    out.append({'page': pi + 1, 'vals': dict(zip(NAMES, v[:3])), 'q': q, 'score': sc, 'mode': 'order'})
                break
    return out + tables_x(text)
def main():
    rows = list(csv.DictReader(open('nesdc_polls_index.csv', encoding='utf-8-sig')))
    out = []
    for x in rows:
        if x['선거구분'] != '제21대 대통령선거' or not ('2025-05-10' <= x['조사종료일'] <= '2025-06-02'): continue
        res = None; ntab = 0
        for n in [n.strip() for n in x['저장파일명'].replace(',', ';').split(';') if n.strip()]:
            tb = tables(open('_txt/' + n[:-4] + '.txt', encoding='utf-8', errors='ignore').read())
            ntab += len(tb)
            if tb:
                best = max(tb, key=lambda t: (t['score'], -t['page']))
                if res is None or best['score'] > res['score']: res = dict(best, file=n)
        out.append({'reg': x['등록번호'], 'org': x['조사기관'], 'end': x['조사종료일'], 'start': x['조사시작일'], 'method': x['조사방법'], 'n': x['조사완료사례수'], 'rr': x['응답률'], 'client': x['조사의뢰자'][:40], 'region': x['조사지역'], 'ntab': ntab, 'res': res})
    json.dump(out, open('_pres_toplines.json', 'w'), ensure_ascii=False, indent=1)
    ok = [o for o in out if o['res']]
    print(len(out), 'parsed', len(ok))
    for o in sorted(out, key=lambda o: o['end']):
        r = o['res']
        print(o['reg'], o['end'][5:], o['org'][:6], o['method'][3:6], ('%g/%g/%g s%d p%d' % (tuple(r['vals'][n] for n in NAMES) + (r['score'], r['page']))) if r else 'FAIL')
if __name__ == '__main__': main()
