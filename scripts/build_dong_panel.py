#!/usr/bin/env python3
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
INCHEON_2026_07_01_REORGANIZATION = {
    ('영종구', '운서1동'): '중구강화군옹진군',
    ('영종구', '운서2동'): '중구강화군옹진군',
    ('제물포구', '율목동'): '중구강화군옹진군',
    ('제물포구', '송현3동'): '동구미추홀구갑',
    ('제물포구', '송림2동'): '동구미추홀구갑',
    ('제물포구', '금창동'): '동구미추홀구갑',
    ('검단구', '아라1동'): '서구병',
    ('검단구', '아라2동'): '서구병',
}


def city_of(sigungu):
    m2 = re.match(r'^(.+[시구군])[갑을병정무]$', sigungu)
    if m2:
        return m2.group(1)
    m = re.match(r'^(.+?시)(.+구)$', sigungu)
    return m.group(1) if m and not sigungu.endswith('자치시') else sigungu


def norm_dong(name):
    return re.sub(r'제(\d)', r'\1', name)


GWANGJU_GU = {'동구', '서구', '남구', '북구', '광산구'}


def norm_sido(sido, sigungu):
    if sido == '전남광주통합특별시':
        return '광주광역시' if sigungu in GWANGJU_GU else '전라남도'
    return sido


def party_of(label):
    return label.split(' ')[0] if ' ' in label else label


def load_2024():
    rows = list(csv.DictReader(open(RAW / 'nec_2024.csv', encoding='cp949')))
    dongs = defaultdict(set)
    for r in rows:
        m = re.match(r'^(.+?)제\d+투$', r['투표구명'])
        if m:
            dongs[(r['시도명'], r['선거구명'])].add(norm_dong(m.group(1)))
    tot = defaultdict(lambda: defaultdict(int))
    for r in rows:
        tot[(r['시도명'], r['선거구명'])][r['후보자']] += int(r['득표수'])
    return dongs, tot


def candidates(sido, sigungu, dongs24):
    city = city_of(sigungu)
    return [k for k in dongs24 if k[0] == sido and (city in k[1] or sigungu in k[1])]


def assign(sido, sigungu, dong, dongs24):
    sido = norm_sido(sido, sigungu)
    dong = norm_dong(dong)
    if sido == '인천광역시':
        district = INCHEON_2026_07_01_REORGANIZATION.get((sigungu, dong))
        if district is not None:
            return (sido, district), 'administrative_crosswalk'
    cands = candidates(sido, sigungu, dongs24)
    hit = [k for k in cands if dong in dongs24[k]]
    if len(hit) == 1:
        return hit[0], 'dong_match'
    if len(hit) > 1:
        return None, 'county_proportional'
    if len(cands) == 1:
        return cands[0], 'single_district_fallback'
    if not cands:
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
        dong_v = defaultdict(lambda: defaultdict(int))
        county_special = defaultdict(lambda: defaultdict(int))
        special_total = 0
        for r in rows:
            key = (r['시도명'], r['구시군명'], r['읍면동명'])
            v = int(r['득표수'] or 0)
            if r[sub] == '':
                if r['읍면동명'] in ('거소·선상투표', '거소투표', '관외사전투표', '재외투표', '국외부재자투표', '잘못 투입·구분된 투표지'):
                    county_special[(r['시도명'], r['구시군명'])][r['후보자']] += v
                    special_total += v if r['후보자'] == '투표수' else 0
                continue
            dong_v[key][r['후보자']] += v
        status = defaultdict(int)
        d_acc = defaultdict(lambda: defaultdict(int))
        county_dist_votes = defaultdict(lambda: defaultdict(int))
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
            total = sum(shares.values())
            for label, votes in lab.items():
                ranks = []
                remaining = votes
                for district, weight in shares.items():
                    allocated, remainder = divmod(votes * weight, total)
                    d_acc[district][label] += allocated
                    remaining -= allocated
                    ranks.append((remainder, district))
                for _, district in sorted(ranks, reverse=True)[:remaining]:
                    d_acc[district][label] += 1
        for d in districts:
            lab = d_acc.get(d, {})
            dem = sum(v for k, v in lab.items() if party_of(k) == DEM)
            con = sum(v for k, v in lab.items() if party_of(k) == CON)
            third = sum(v for k, v in lab.items() if k not in META and party_of(k) not in (DEM, CON))
            dist[d][el] = {'electors': lab.get('선거인수', 0), 'votes': lab.get('투표수', 0), 'dem': dem, 'con': con, 'third': third}
        tv = sum(l.get('투표수', 0) for l in dong_v.values())
        status.setdefault('no_candidate_district', 0)
        report['elections'][el] = {'file': fname, 'sha256': hashlib.sha256((RAW / fname).read_bytes()).hexdigest(),
                                   'dongs': len(dong_v), 'map_status': dict(status),
                                   'unassigned_vote_share': sum(u[3] for u in unassigned) / tv if tv else 0,
                                   'county_level_votes': special_total, 'county_level_votes_not_allocated': lost_special,
                                   'unassigned_examples': unassigned[:12]}
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
