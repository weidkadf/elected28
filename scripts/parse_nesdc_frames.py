import csv, re, json, sys, collections
TOT = re.compile(r'^\s*[■▣◆●▶\[\(\|]*\s*(전\s*체|합\s*계|전\s*국|TOTAL|Total|total)\b')
NUM = re.compile(r'\(?-?\d[\d,]*\.?\d*\)?%?')
SUP = re.compile(r'지원|안정|힘을?실어|뒷받침|재창출|연장|유지')
CHK = re.compile(r'견제|심판|교체')
REG = [('서울', r'서울'), ('인천/경기', r'(인천|경기)[/·,]?(경기|인천)|경인권?|수도권'), ('대전/세종/충청', r'(대전|충청|세종)[/·,]?(세종|충청|대전)|충청권?'),
       ('광주/전라', r'(광주|전라|전남|전북|호남)[/·,]?(전라|전남|전북|광주)?|호남권?'), ('대구/경북', r'(대구|경북)[/·,]?(경북|대구)|TK'),
       ('부산/울산/경남', r'(부산|울산|경남)[/·,]?(울산|경남|부산)|부울경|PK'), ('강원/제주', r'(강원|제주)[/·,]?(제주|강원)'), ('강원', r'강원'), ('제주', r'제주')]
def vals(line):
    out = []; counts = []; started = False
    for m in NUM.finditer(line):
        raw = m.group().replace('%', '')
        num = raw.strip('()').replace(',', '')
        try: x = float(num)
        except ValueError: continue
        if not started and ('(' in raw or ',' in raw or ('.' not in raw and x >= 101)):
            counts.append(x); continue
        if '(' in raw: break
        started = True; out.append(x)
    return counts, out
def label(line):
    m = NUM.search(line)
    return re.sub(r'\s', '', line[:m.start()] if m else line)
def region_of(lab):
    lab = re.sub(r'^(지역별?|권역별?|거주지역?|거주지)', '', lab)
    lab = re.sub(r'^[■▣◆●▶\[\(\|]+|[\]\)]+$', '', lab)
    lab = re.sub(r'(권|지역)$', '', lab)
    if lab in ('호남', '광주전라', '광주전남전북'): return '광주/전라'
    if lab in ('충청', '대전세종충청', '대전충청세종', '대전충청'): return '대전/세종/충청'
    if lab in ('부울경', 'PK', '부산울산경남'): return '부산/울산/경남'
    if lab in ('TK', '대구경북'): return '대구/경북'
    if lab in ('수도', '경인', '인천경기', '경기인천'): return '인천/경기'
    if lab in ('강원제주',): return '강원/제주'
    toks = set(t for t in re.split(r'[/·,ㆍ\.‧・]', lab) if t)
    if not toks or len(lab) > 14: return None
    if toks == {'서울'}: return '서울'
    if toks == {'인천', '경기'}: return '인천/경기'
    if len(toks) >= 2 and toks <= {'대전', '세종', '충청', '충남', '충북'}: return '대전/세종/충청'
    if len(toks) >= 2 and toks <= {'광주', '전라', '전남', '전북', '호남'}: return '광주/전라'
    if toks == {'대구', '경북'}: return '대구/경북'
    if len(toks) >= 2 and toks <= {'부산', '울산', '경남'}: return '부산/울산/경남'
    if toks == {'강원', '제주'}: return '강원/제주'
    if toks == {'강원'}: return '강원'
    if toks == {'제주'}: return '제주'
    return None
def xpos(lines, pat):
    best = None
    for ln in lines:
        for m in pat.finditer(ln):
            if best is None or m.start() < best: best = m.start()
    return best
def parse(text):
    frames, xt = [], []
    for pi, page in enumerate(text.split('\f')):
        lines = page.split('\n')
        tots = [j for j, l in enumerate(lines) if TOT.search(l)]
        for j in tots:
            head = lines[max(0, j - 9):j]
            hs = ' '.join(head); hc = re.sub(r'\s', '', hs)
            cnt, v = vals(TOT.sub('', lines[j], 1))
            title = ' '.join(x.strip() for x in lines[max(0, j - 22):max(0, j - 9)] + head if len(re.findall('[가-힣]', x)) >= 5)[-300:]
            # (B) frame table with region rows
            xs, xc = xpos(head[-7:], SUP), xpos(head[-7:], CHK)
            if xs is not None and xc is not None and xs != xc and len(v) >= 2 and 55 <= v[0] + v[1] <= 100 and not re.search(r'이재명|김문수|민주당|국민의힘', re.sub(r'\s', '', ' '.join(head[-7:]))):
                order = ('s', 'c') if xs < xc else ('c', 's')
                rec = {'page': pi + 1, 'title': title, 'nat': dict(zip(order, v[:2])), 'n': cnt[-1] if cnt else None, 'reg': {}}
                for l in lines[j + 1:j + 60]:
                    r = region_of(label(l))
                    if r and r not in rec['reg']:
                        c2, v2 = vals(l)
                        if len(v2) >= 2: rec['reg'][r] = dict(zip(order, v2[:2]), n=c2[-1] if c2 else None)
                frames.append(rec)
            # (A) party table with frame rows
            hh = head[-7:]
            xd = xpos(hh, re.compile('민주')); xk = xpos(hh, re.compile(r'국민의|국민\s*의'))
            if xd is not None and xk is not None and xd != xk and len(v) >= 2:
                order = ('D', 'C') if xd < xk else ('C', 'D')
                rows = {}
                for l in lines[j + 1:j + 90]:
                    lab = label(l)
                    if len(lab) > 30 or not lab: continue
                    ks, kc = bool(SUP.search(lab)), bool(CHK.search(lab))
                    if ks == kc: continue
                    c2, v2 = vals(l)
                    if len(v2) >= 2 and c2 and ('s' if ks else 'c') not in rows:
                        rows['s' if ks else 'c'] = dict(zip(order, v2[:2]), n=c2[-1], lab=lab[-16:])
                if len(rows) == 2:
                    xt.append({'page': pi + 1, 'title': title, 'tot': dict(zip(order, v[:2])), 'n': cnt[-1] if cnt else None, 'rows': rows})
    return frames, xt
def main():
    out = []
    for x in csv.DictReader(open('nesdc_polls_index.csv', encoding='utf-8-sig')):
        F, X = [], []
        for n in [n.strip() for n in x['저장파일명'].replace(',', ';').split(';') if n.strip()]:
            f, t = parse(open('_txt/' + n[:-4] + '.txt', encoding='utf-8', errors='ignore').read())
            F += f; X += t
        if F or X:
            out.append({'reg': x['등록번호'], 'election': x['선거구분'], 'org': x['조사기관'], 'method': x['조사방법'], 'start': x['조사시작일'], 'end': x['조사종료일'],
                        'n': x['조사완료사례수'], 'region': x['조사지역'], 'frames': F, 'xtabs': X})
    json.dump(out, open('_frames.json', 'w'), ensure_ascii=False)
    c = collections.Counter(); 
    for o in out:
        c[(o['election'][:6], 'frame')] += bool(o['frames']); c[(o['election'][:6], 'frame_with_regions')] += any(len(f['reg']) >= 5 for f in o['frames']); c[(o['election'][:6], 'xtab')] += bool(o['xtabs'])
    print(len(out), sorted(c.items()))
    import random; random.seed(1)
    for o in random.sample(out, 8):
        f = o['frames'][0] if o['frames'] else None; t = o['xtabs'][0] if o['xtabs'] else None
        print(o['reg'], o['org'][:8], o['end'], '| F:', (f['title'][-70:], f['nat'], len(f['reg'])) if f else None, '| X:', (t['title'][-50:], t['rows']) if t else None)
if __name__ == '__main__': main()
