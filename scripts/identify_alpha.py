#!/usr/bin/env python3
"""Three routes to alpha (frame-to-vote transfer), then a combined posterior and a seat distribution.

1. micro  : frame x party crosstabs in NESDC result tables -> composition slope
            alpha_micro = (1-k) (v_demside - v_other) q(1-q) / (p(1-p))
2. region : pooled NESDC regional frame deviations (2024 general, 2025 presidential, 2026 local)
            -> does the vote move more where the frame moved more? (free intercept per pair)
3. prior  : uniform-swing prior alpha ~ N(1, 0.5^2) (assumption), combined on a grid.
Input : data/nesdc/frame_tables.json (scripts/parse_nesdc_frames.py), data/district_panel.csv
Output: outputs/alpha_identification.json
"""
import csv, json, math, re, sys, statistics as st
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_2020_2024 as B  # noqa: E402
import analyze_dong_panel as A  # noqa: E402
from model import REGIONAL_SCOPE_MEMBERS  # noqa: E402
SCOPE = {m: s for s, ms in REGIONAL_SCOPE_MEMBERS.items() for m in ms}
lg = lambda p: math.log(p / (1 - p))
GOV_CHANGE = '2025-06-04'            # before: PPP government (Dem side = check/교체); after: Dem government (Dem side = support)
FRAME_OK = re.compile(r'정권교체|정권을?교체|견제|국정안정|힘을?실어|지원론|심판론|정권심판|정부심판|여당심판|정부.{0,8}지원|재창출')
WINDOWS = {'gen2024': ('제22대 국회의원선거', '2024-01-01', '2024-04-09'), 'pres2025': ('제21대 대통령선거', '2025-04-04', '2025-06-02'),
           'gov2026': ('제9회 전국동시지방선거', '2026-03-01', '2026-06-02')}
DEFF = 1.5
PRIOR = (1.0, 0.5)
MICRO_STRUCT_SD = 0.2


def dem_side(end):
    return 'c' if end < GOV_CHANGE else 's'


def party_order_from_header(title):
    """True when the header names 더불어민주당 before 국민의힘. Two-line headers ('더불어' / '민주당') made the parser
    place 민주 by its second line and swap the two columns in tables that also list 조국혁신당 etc."""
    h = re.sub(r'\s', '', title); i, j = h.rfind('더불어'), h.rfind('국민의')
    return None if i < 0 or j < 0 else i < j


def fix_party_order(polls):
    sw = lambda d: {('C' if k == 'D' else 'D' if k == 'C' else k): v for k, v in d.items()}
    fixed = []
    for o in polls:
        for t in o['xtabs']:
            dem_first = party_order_from_header(t['title'])
            if dem_first is not None and dem_first != (next(iter(t['tot'])) == 'D'):
                t['tot'] = sw(t['tot']); t['rows'] = {k: sw(v) for k, v in t['rows'].items()}
                fixed.append({'reg': o['reg'], 'page': t['page']})
    return fixed


JK_FILE = ROOT / 'data/nesdc/frame_xtab_jk.json'


def jk_key(o, t):
    return f"{o['reg']}:{t['page']}:{t['tot']['D']}:{t['tot']['C']}"


def add_jk(polls, jk):
    """Dem side = 더불어민주당 + 조국혁신당 (user decision 2026-11-14). Run after fix_party_order. A crosstab whose header names
    조국혁신당 but whose 조국 column was not read (scripts/fetch_xtab_jk.py) is skipped so every table uses the same definition."""
    added, skipped = 0, []
    for o in polls:
        for t in o['xtabs']:
            if '조국' not in re.sub(r'\s', '', t['title']): continue
            j = jk.get(jk_key(o, t))
            if j is None:
                t['skip'] = True; skipped.append(jk_key(o, t)); continue
            t['tot']['D'] += j['J']['tot']
            for k, r in t['rows'].items(): r['D'] += j['J'][k]
            t['jk'] = j['J']; added += 1
    return {'tables_with_jk_added': added, 'tables_skipped_jk_unread': skipped}


def micro(polls):
    rows, dropped = [], 0
    for o in polls:
        best = None
        for t in o['xtabs']:
            if t.get('skip'): continue
            r = t['rows']; ds = dem_side(o['end']); os_ = 's' if ds == 'c' else 'c'
            try:
                vd = r[ds]['D'] / (r[ds]['D'] + r[ds]['C']); vo = r[os_]['D'] / (r[os_]['D'] + r[os_]['C'])
                p = t['tot']['D'] / (t['tot']['D'] + t['tot']['C'])
                n = t['n'] or (r['s']['n'] + r['c']['n']) / 0.88
                k = max(0.0, 1 - (r['s']['n'] + r['c']['n']) / n)
                q = r[ds]['n'] / (r['s']['n'] + r['c']['n'])
            except (ZeroDivisionError, KeyError, TypeError):
                continue
            if min(r['s']['n'], r['c']['n']) < 80 or vd - vo < 0.3 or not (0.2 < p < 0.8) or not (0.15 < q < 0.85) or k > 0.4:
                continue
            a = (1 - k) * (vd - vo) * q * (1 - q) / (p * (1 - p))
            cand = {'reg': o['reg'], 'org': o['org'], 'end': o['end'], 'election': o['election'], 'alpha': round(a, 4), 'v_dem_side': round(vd, 3),
                    'v_other_side': round(vo, 3), 'q': round(q, 3), 'p': round(p, 3), 'k': round(k, 3), 'jk_in_dem': t.get('jk')}
            if best is None: best = cand
        if best: rows.append(best)
        elif o['xtabs']: dropped += 1
    al = [r['alpha'] for r in rows]
    by_org = defaultdict(list)
    for r in rows: by_org[r['org']].append(r['alpha'])
    om = [st.mean(v) for v in by_org.values()]
    by_el = defaultdict(list)
    for r in rows: by_el[r['election']].append(r['alpha'])
    return {'n_polls': len(rows), 'n_pollsters': len(om), 'dropped_parse_or_filter': dropped, 'mean': round(st.mean(al), 4), 'median': round(st.median(al), 4),
            'sd_between_polls': round(st.pstdev(al), 4), 'mean_of_pollster_means': round(st.mean(om), 4), 'sd_between_pollsters': round(st.pstdev(om), 4),
            'by_election': {k: {'n': len(v), 'mean': round(st.mean(v), 4)} for k, v in by_el.items()},
            'mean_conditional_vote': {'dem_side': round(st.mean(r['v_dem_side'] for r in rows), 3), 'other_side': round(st.mean(r['v_other_side'] for r in rows), 3)},
            'polls': rows,
            'meaning': 'vote change implied by moving respondents between frame answers while each answer group keeps its party split; party column is party support or vote intention depending on the table'}


def regional(polls):
    dev = {}
    for w, (el, lo, hi) in WINDOWS.items():
        acc = defaultdict(lambda: [0.0, 0.0]); used = 0
        for o in polls:
            if o['election'] != el or not (lo <= o['end'] <= hi) or '전국' not in o['region']:
                continue
            cands = [f for f in o['frames'] if len(f['reg']) >= 5 and FRAME_OK.search(re.sub(r'\s', '', f['title'])) and '헌법재판' not in f['title']]
            if not cands: continue
            f = max(cands, key=lambda f: len(f['reg'])); ds = dem_side(o['end']); used += 1
            qn = f['nat'][ds] / (f['nat']['s'] + f['nat']['c'])
            for name, r in f['reg'].items():
                if r['s'] + r['c'] <= 0 or not r.get('n') or r['n'] < 30: continue
                q = min(max(r[ds] / (r['s'] + r['c']), 0.03), 0.97)
                var = DEFF / (r['n'] * (r['s'] + r['c']) / 100 * q * (1 - q))
                for sc in (['강원', '제주'] if name == '강원/제주' else [name]):
                    acc[sc][0] += (lg(q) - lg(qn)) / var; acc[sc][1] += 1 / var
        dev[w] = {'n_polls': used, 'dev': {s: a[0] / a[1] for s, a in acc.items()}, 'se': {s: math.sqrt(1 / a[1]) for s, a in acc.items()}}
    P = A.panel(); f = A.f
    pairs, info = {}, {}
    for name, (w0, w1, c0, c1) in {'gen2024_to_pres2025': ('gen2024', 'pres2025', 'gen2024_two_party_dem', 'pres2025_two_party_dem'),
                                   'gen2024_to_gov2026': ('gen2024', 'gov2026', 'gen2024_two_party_dem', 'gov2026_two_party_dem')}.items():
        xs = {s: dev[w1]['dev'][s] - dev[w0]['dev'][s] for s in REGIONAL_SCOPE_MEMBERS if s in dev[w1]['dev'] and s in dev[w0]['dev']}
        se = {s: math.hypot(dev[w1]['se'][s], dev[w0]['se'][s]) for s in xs}
        y, x, g = [], [], []
        for r in P:
            a, b = f(r[c0]), f(r[c1]); sc = SCOPE[r['sido']]
            if a is None or b is None or not (0.15 < a < 0.85 and 0.15 < b < 0.85) or sc not in xs: continue
            y.append(lg(b) - lg(a)); x.append(xs[sc]); g.append(r['sido'])
        y, x, g = np.array(y), np.array(x), np.array(g)
        fit = B.fit(y, x, g); ci, _ = B.profile_ci(y, x, g, fit, lo=-4, hi=5, step=0.05)
        vx = float(np.var(list(xs.values()))); noise = float(np.mean([v * v for v in se.values()]))
        pairs[name] = (y, x, g)
        info[name] = {'n_districts': len(y), 'x_by_scope': {s: round(v, 4) for s, v in xs.items()}, 'x_se_by_scope': {s: round(v, 4) for s, v in se.items()},
                      'x_sd_across_scopes': round(math.sqrt(vx), 4), 'x_reliability': round(max(0.0, 1 - noise / vx), 3) if vx > 0 else None,
                      'alpha': round(float(fit['alpha']), 3), 'ci95': ci, 'intercept': round(float(fit['c']), 3)}
    grid = np.round(np.arange(-1.0, 3.0001, 0.05), 2)
    pl = list(pairs.values())
    best = A.joint_fit(pl)
    prof = np.array([A.joint_fit(pl, False, float(a))['nll'] for a in grid])
    inside = grid[prof - prof.min() <= 1.920729]
    joint = {'alpha': round(float(best['alpha']), 3), 'ci95': [float(inside.min()), float(inside.max())], 'grid': grid.tolist(), 'profile_nll': (prof - prof.min()).tolist()}
    one = [pairs['gen2024_to_gov2026']]
    prof1 = np.array([A.joint_fit(one, False, float(a))['nll'] for a in grid])
    joint['profile_nll_same_wording_pair_only'] = (prof1 - prof1.min()).tolist()
    return {'windows': {w: {'n_polls': d['n_polls'], 'dev': {s: round(v, 4) for s, v in d['dev'].items()}, 'se': {s: round(v, 4) for s, v in d['se'].items()}} for w, d in dev.items()},
            'pairs': info, 'joint_free_intercepts': joint,
            'note': 'x = change in regional deviation of the Dem-direction frame share; national change is absorbed by the pair intercept'}


def combine(mic, regn):
    grid = np.array(regn['joint_free_intercepts']['grid']); nll_r = np.array(regn['joint_free_intercepts']['profile_nll'])
    sd_m = math.hypot(mic['sd_between_pollsters'] / math.sqrt(mic['n_pollsters']), MICRO_STRUCT_SD)
    ll_m = -0.5 * ((grid - mic['mean_of_pollster_means']) / sd_m) ** 2
    ll_p = -0.5 * ((grid - PRIOR[0]) / PRIOR[1]) ** 2
    def post(ll):
        w = np.exp(ll - ll.max()); w /= w.sum(); c = np.cumsum(w)
        return {'mean': round(float((grid * w).sum()), 3), 'ci95': [float(grid[np.searchsorted(c, 0.025)]), float(grid[np.searchsorted(c, 0.975)])],
                'p_alpha_above_0.2': round(float(w[grid > 0.2].sum()), 4)}, w
    nll_1 = np.array(regn['joint_free_intercepts']['profile_nll_same_wording_pair_only'])
    out = {}
    for name, ll in {'all_three_excluding_presidential_pair': ll_m - nll_1 + ll_p, 'region_only': -nll_r, 'micro_only': ll_m, 'prior_only': ll_p, 'micro_plus_region': ll_m - nll_r,
                     'prior_plus_region': ll_p - nll_r, 'all_three': ll_m - nll_r + ll_p}.items():
        out[name], w = post(ll)
        if name == 'all_three': wall = w
        if name == 'micro_plus_region': wmr = w
        if name == 'all_three_excluding_presidential_pair': wex = w
    return {'grid': grid.tolist(), 'micro_sd_used': round(sd_m, 4), 'prior': {'mean': PRIOR[0], 'sd': PRIOR[1], 'basis': 'assumption: uniform logit swing'},
            'micro_structural_sd': MICRO_STRUCT_SD, 'posteriors': out, 'weights_all_three': wall.tolist(), 'weights_micro_plus_region': wmr.tolist(), 'weights_all_three_excluding_presidential_pair': wex.tolist()}


def seats(comb):
    import forecast_v030 as F, forecast_v050 as V
    from datetime import date
    cfg = F.load_json('config/forecast_v050.json'); s = F.sigmas(cfg)
    change, c_agg = V.frame_change(cfg, cfg['frame_inputs']['aggregator']['wording_classes_main'])
    days = (date.fromisoformat(cfg['target_election_date']) - date.fromisoformat(max(p['fieldwork_end'] for p in c_agg['polls_used']))).days
    comp, _ = V.composite(cfg)
    sim = V.CompositeSimulator(F.read_baseline(ROOT / 'data/baseline_2024.csv'), cfg['draws'], cfg['seed'], F.REGIONAL_SCOPE_MEMBERS, comp)
    grid = np.array(comb['grid']); res = {}
    for key in ('weights_all_three', 'weights_micro_plus_region', 'weights_all_three_excluding_presidential_pair'):
        w = np.array(comb[key]); keep = (w > 1e-4) & (grid >= 0)
        dem, con, ww = [], [], []
        for a, wi in zip(grid[keep], w[keep]):
            r = sim.run(float(a), change, F.sigma_national(float(a), days, s), s['region'], s['district'])
            dem.append(r['dem_seats']); con.append(r['con_seats']); ww.append(np.full(len(r['dem_seats']), wi))
        dem, con, ww = np.concatenate(dem), np.concatenate(con), np.concatenate(ww); ww /= ww.sum()
        o = np.argsort(dem); cd = np.cumsum(ww[o]); qd = lambda p: int(dem[o][np.searchsorted(cd, p)])
        res[key.replace('weights_', '')] = {'dem_mean': round(float((dem * ww).sum()), 1), 'con_mean': round(float((con * ww).sum()), 1),
                                             'dem_p10_p50_p90': [qd(.1), qd(.5), qd(.9)], 'p_dem_district_majority': round(float(ww[dem >= 128].sum()), 4),
                                             'p_con_district_majority': round(float(ww[con >= 128].sum()), 4), 'alpha_mass_below_0_dropped': round(float(w[grid < 0].sum()), 4)}
    res['condition'] = 'current frame polls held to election day plus time drift sigma(d); 254 district seats only; 2024 boundaries; candidates unknown'
    return res


def main():
    polls = json.loads((ROOT / 'data/nesdc/frame_tables.json').read_text(encoding='utf-8'))
    fixed = fix_party_order(polls)
    mic_dem_only = micro(json.loads(json.dumps(polls)))
    jk_info = add_jk(polls, json.loads(JK_FILE.read_text(encoding='utf-8'))['tables'])
    mic = micro(polls); mic['party_column_order_fixed'] = fixed
    mic['dem_side'] = '더불어민주당 + 조국혁신당 (조국 열이 있는 표); 사용자 결정 2026-11-14'; mic['jk'] = jk_info
    mic['comparison_dem_only'] = {k: mic_dem_only[k] for k in ('n_polls', 'n_pollsters', 'mean', 'mean_of_pollster_means', 'sd_between_pollsters', 'by_election')}
    regn = regional(polls); comb = combine(mic, regn); sd = seats(comb)
    out = {'schema_version': 'alpha_identification_1', 'micro': mic, 'regional': regn, 'combined': comb, 'seat_distribution': sd,
           'caveats': ['micro slope is cross-sectional (composition), not a causal over-time effect', 'automatic PDF parsing; frame wording differs by pollster and election (지원/견제, 심판/안정, 정권교체/유지)',
                       'regional x is noisy; reliability reported per pair', 'prior is an assumption; results without it are reported']}
    (ROOT / 'outputs/alpha_identification.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'micro': {k: v for k, v in mic.items() if k not in ('polls', 'meaning')}, 'windows': {w: (d['n_polls'], d['se']) for w, d in regn['windows'].items()},
                      'pairs': regn['pairs'], 'joint': {k: regn['joint_free_intercepts'][k] for k in ('alpha', 'ci95')}, 'post': comb['posteriors'], 'micro_sd': comb['micro_sd_used'], 'seats': sd}, ensure_ascii=False, indent=0))


if __name__ == '__main__':
    main()
