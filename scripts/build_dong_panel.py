#!/usr/bin/env python3
"""Dong-level panel: 2025 presidential and 2026 local results mapped to the 254 districts of 2024 (v0.4.0).

Sources (data.go.kr, NEC): data/raw/nec_2024.csv (cp949), nec_presidential_20250603.csv,
nec_local_governor_20260603.csv, nec_local_mayor_20260603.csv (utf-8-sig).

Mapping rule
* The 2024 file's 법정읍면동명 column is unreliable in multi-county districts (rows of several counties
  share one label), so the dong name of a 2024 row is taken from the election-day 투표구명
  ('영월읍제1투' -> '영월읍'). District -> dong set comes from that.
* A 2025/2026 dong (시도, 구시군, 읍면동) belongs to the 2024 district of the same 시도 whose name contains the
  city/county name and whose dong set contains the dong name. A dong not found (renamed/new after 2024)
  falls back to the only candidate district when the city/county is not split; otherwise it is left
  unassigned and reported.
* County-level rows without a dong (관외사전, 거소·선상, 재외, 잘못 투입) are allocated to the districts of that
  county in proportion to each district's share of the county's dong-attributed total votes.
Outputs: data/dong_panel.csv (dong x election), data/district_panel.csv (254 districts), outputs/dong_panel_report.json
"""
from __future__ import annotations
import csv, hashlib, json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
META = {'선거인수', '투표수', '무효 투표수', '기권자수'}
DEM = '더불어민주당'
CON = '국민의힘'
ELECTIONS = {
    'pres2025': ('nec_presidential_20250603.csv', '투표구명'),
    'gov2026': ('nec_local_governor_20260603.csv', '구분명'),
    'mayor2026': ('nec_local_mayor_20260603.csv', '구분명'),
}


def city_of(sigungu):
    """'수원시장안구' -> '수원시'; '종로구' -> '종로구'; '세종특별자치시' -> '세종특별자치시'."""
    m2 = re.match(r'^(.+[시구군])[갑을병정무]$', sigungu)   # NEC sub-office labels such as '화성시을'
    if m2:
        return m2.group(1)
    m = re.match(r'^(.+?시)(.+구)$', sigungu)
    return m.group(1) if m and not sigungu.endswith('자치시') else sigungu


def norm_dong(name):
    """'둔촌제1동' and '둔촌1동' are the same dong."""
    return re.sub(r'제(\d)', r'\1', name)


GWANGJU_GU = {'동구', '서구', '남구', '북구', '광산구'}


def norm_sido(sido, sigungu):
    """2026 merged 전남광주통합특별시 back to the 2024 시도 of each county."""
    if sido == '전남광주통합특별시':
        return '광주광역시' if sigungu in GWANGJU_GU else '전라남도'
    return sido


def party_of(label):
    return label.split(' ')[0] if ' ' in label else label


def load_2024():
    rows = list(csv.DictReader(open(RAW / 'nec_2024.csv', encoding='cp949')))
    dongs = defaultdict(set)          # (sido, district) -> dong names
    for r in rows:
        m = re.match(r'^(.+?)제\d+투$', r['투표구명'])
        if m:
            dongs[(r['시도명'], r['선거구명'])].add(norm_dong(m.group(1)))
    tot = defaultdict(lambda: defaultdict(int))   # district totals by label
    for r in rows:
        tot[(r['시도명'], r['선거구명'])][r['후보자']] += int(r['득표수'])
    return dongs, tot


def candidates(sido, sigungu, dongs24):
    city = city_of(sigungu)
    return [k for k in dongs24 if k[0] == sido and (city in k[1] or sigungu in k[1])]


def assign(sido, sigungu, dong, dongs24):
    sido = norm_sido(sido, sigungu)
    dong = norm_dong(dong)
    cands = candidates(sido, sigungu, dongs24)
    hit = [k for k in cands if dong in dongs24[k]]
    if len(hit) == 1:
        return hit[0], 'dong_match'
    if len(hit) > 1:
        return None, 'county_proportional'
    if len(cands) == 1:
        return cands[0], 'single_district_fallback'
    if not cands:
        # county renamed or re-drawn after 2024 (e.g. Incheon 2026): unique dong-name match within the 시도
        wide = [k for k in dongs24 if k[0] == sido and dong in dongs24[k]]
        if len(wide) == 1:
            return wide[0], 'sido_wide_dong_match'
        return None, 'no_candidate_district'
    return None, 'county_proportional'


def main():
    dongs24, tot24 = load_2024()
    districts = sorted(dongs24)
    report = {'districts_2024': len(districts), 'elections': {}}
    dist = {d: {} for d in districts}
    dong_rows = []
    for el, (fname, sub) in ELECTIONS.items():
        rows = list(csv.DictReader(open(RAW / fname, encoding='utf-8-sig')))
        dong_v = defaultdict(lambda: defaultdict(int))     # (sido, sigungu, dong) -> label -> votes
        county_special = defaultdict(lambda: defaultdict(int))
        special_total = 0
        for r in rows:
            key = (r['시도명'], r['구시군명'], r['읍면동명'])
            v = int(r['득표수'] or 0)
            if r[sub] == '':
                # dong-level total row (pres file) or a county-level special row
                if r['읍면동명'] in ('거소·선상투표', '거소투표', '관외사전투표', '재외투표', '국외부재자투표', '잘못 투입·구분된 투표지'):
                    county_special[(r['시도명'], r['구시군명'])][r['후보자']] += v
                    special_total += v if r['후보자'] == '투표수' else 0
                continue
            dong_v[key][r['후보자']] += v
        status = defaultdict(int)
        d_acc = defaultdict(lambda: defaultdict(float))
        county_dist_votes = defaultdict(lambda: defaultdict(float))
        unassigned = []
        for (sido, sgg, dong), lab in dong_v.items():
            d, st = assign(sido, sgg, dong, dongs24)
            status[st] += 1
            dem = sum(v for k, v in lab.items() if party_of(k) == DEM)
            con = sum(v for k, v in lab.items() if party_of(k) == CON)
            dong_rows.append({'election': el, 'sido': sido, 'sigungu': sgg, 'dong': dong,
                              'district_2024': d[1] if d else '', 'map_status': st,
                              'electors': lab.get('선거인수', 0), 'votes': lab.get('투표수', 0), 'dem': dem, 'con': con})
            if d is None and st == 'county_proportional':
                # new/renamed dong inside a split city: treat like a county-level row
                for k, v in lab.items():
                    county_special[(sido, sgg)][k] += v
                continue
            if d is None:
                unassigned.append([sido, sgg, dong, lab.get('투표수', 0)])
                continue
            for k, v in lab.items():
                d_acc[d][k] += v
            county_dist_votes[(sido, sgg)][d] += lab.get('투표수', 0)
        lost_special = 0
        for cty, lab in county_special.items():
            shares = county_dist_votes.get(cty)
            if not shares:
                lost_special += lab.get('투표수', 0)
                continue
            s = sum(shares.values())
            for d, w in shares.items():
                for k, v in lab.items():
                    d_acc[d][k] += v * w / s
        for d in districts:
            lab = d_acc.get(d, {})
            dem = sum(v for k, v in lab.items() if party_of(k) == DEM)
            con = sum(v for k, v in lab.items() if party_of(k) == CON)
            third = sum(v for k, v in lab.items() if k not in META and party_of(k) not in (DEM, CON))
            dist[d][el] = {'electors': lab.get('선거인수', 0), 'votes': lab.get('투표수', 0), 'dem': dem, 'con': con, 'third': third}
        tv = sum(l.get('투표수', 0) for l in dong_v.values())
        report['elections'][el] = {'file': fname, 'sha256': hashlib.sha256((RAW / fname).read_bytes()).hexdigest(),
                                   'dongs': len(dong_v), 'map_status': dict(status),
                                   'unassigned_vote_share': sum(u[3] for u in unassigned) / tv if tv else 0,
                                   'county_level_votes': special_total, 'county_level_votes_not_allocated': lost_special,
                                   'unassigned_examples': unassigned[:12]}
    # 2024 district totals (official, all vote modes)
    with open(ROOT / 'data' / 'district_panel.csv', 'w', encoding='utf-8', newline='') as f:
        cols = ['sido', 'district_2024']
        for el in ['gen2024', *ELECTIONS]:
            cols += [f'{el}_{c}' for c in ('electors', 'votes', 'dem', 'con', 'third', 'two_party_dem', 'turnout')]
        w = csv.writer(f)
        w.writerow(cols)
        for d in districts:
            lab = tot24[d]
            dem = sum(v for k, v in lab.items() if party_of(k) == DEM)
            con = sum(v for k, v in lab.items() if party_of(k) == CON)
            third = sum(v for k, v in lab.items() if k not in META and party_of(k) not in (DEM, CON))
            recs = {'gen2024': {'electors': lab['선거인수'], 'votes': lab['투표수'], 'dem': dem, 'con': con, 'third': third}, **dist[d]}
            row = list(d)
            for el in ['gen2024', *ELECTIONS]:
                r = recs[el]
                tp = r['dem'] / (r['dem'] + r['con']) if r['dem'] > 0 and r['con'] > 0 else ''
                to = r['votes'] / r['electors'] if r['electors'] else ''
                row += [round(r['electors']), round(r['votes']), round(r['dem']), round(r['con']), round(r['third']),
                        round(tp, 6) if tp != '' else '', round(to, 6) if to != '' else '']
            w.writerow(row)
    with open(ROOT / 'data' / 'dong_panel.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(dong_rows[0].keys()))
        w.writeheader()
        w.writerows(dong_rows)
    (ROOT / 'outputs' / 'dong_panel_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ('dongs', 'map_status', 'unassigned_vote_share')}
                      for k, v in report['elections'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
