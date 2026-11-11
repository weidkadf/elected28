#!/usr/bin/env python3
"""Use the dong-built district panel (2024 general, 2025 presidential, 2026 local) three ways (v0.4.0).

1. alpha: second election pair 2024 general -> 2026 governor vote, frames 2024-03 (578-580) -> 2026-05
   (662-664), both likely-voter adjusted; fitted alone and pooled with the 2020->2024 pair.
2. turnout: actual district turnout in the three elections and how the presidential->local drop relates
   to district partisanship (descriptive check of the survey-based turnout weights).
3. baseline: alpha curve restarted from the June 2026 governor vote with the frame change since May 2026.
Cross-type caveat: a governor vote is not a National Assembly vote (17 province-level candidates).
"""
from __future__ import annotations
import csv, json, math, sys
from datetime import date
from pathlib import Path
import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_2020_2024 as B  # noqa: E402
import forecast_v030 as F  # noqa: E402
import turnout as TO  # noqa: E402
from model import REGIONAL_SCOPE_MEMBERS, read_baseline  # noqa: E402

B.ELECTION[2026] = '2026-06-03'
B.COMPONENT[2026] = 'support'
B.WAVES[2026] = ['662', '663', '664']
SCOPE = {m: s for s, ms in REGIONAL_SCOPE_MEMBERS.items() for m in ms}
lg = lambda p: math.log(p / (1 - p))


def panel():
    return list(csv.DictReader(open(ROOT / 'data/district_panel.csv', encoding='utf-8')))


def f(x):
    return float(x) if x != '' else None


def joint_nll(theta, pairs, fix_c0):
    """pairs: list of (y, x, g). theta = [alpha, (c_k)..., (ln s_r, ln s_d)_k...]."""
    a = theta[0]
    k = len(pairs)
    cs = [0.0] * k if fix_c0 else list(theta[1:1 + k])
    rest = theta[1:] if fix_c0 else theta[1 + k:]
    tot = 0.0
    for i, (y, x, g) in enumerate(pairs):
        th = [cs[i], a, rest[2 * i], rest[2 * i + 1]]
        tot += B.negloglik(th, y, x, g)
    return tot


def joint_fit(pairs, fix_c0=False, fix_alpha=None):
    k = len(pairs)

    def fn(th):
        full = ([fix_alpha] if fix_alpha is not None else []) + list(th)
        return joint_nll(full, pairs, fix_c0)
    start = ([] if fix_alpha is not None else [0.3]) + ([] if fix_c0 else [0.0] * k) + [math.log(.1), math.log(.2)] * k
    res = minimize(fn, start, method='Nelder-Mead', options={'xatol': 1e-6, 'fatol': 1e-8, 'maxiter': 40000, 'maxfev': 40000})
    full = ([fix_alpha] if fix_alpha is not None else []) + list(res.x)
    out = {'alpha': full[0], 'nll': float(res.fun)}
    if not fix_c0:
        out['c'] = full[1:1 + k]
    rest = full[1:] if fix_c0 else full[1 + k:]
    out['sigma_region'] = [math.exp(rest[2 * i]) for i in range(k)]
    out['sigma_district'] = [math.exp(rest[2 * i + 1]) for i in range(k)]
    return out


def joint_ci(pairs, best, fix_c0=False, lo=-3, hi=4, step=0.05):
    grid = np.arange(lo, hi + 1e-9, step)
    prof = np.array([joint_fit(pairs, fix_c0, float(a))['nll'] for a in grid])
    inside = grid[prof - best['nll'] <= 1.920729]
    return [round(float(inside.min()), 2), round(float(inside.max()), 2)] if len(inside) else [None, None]


def main():
    rows = panel()
    # ---------- 1. alpha, pair 2024 -> 2026 governor
    c24, a24, _ = B.frame_coordinates(2024)
    c26, a26, _ = B.frame_coordinates(2026)
    x_scope = {s: c26[s] - c24[s] for s in REGIONAL_SCOPE_MEMBERS}
    ys, xs, gs, used = [], [], [], []
    for r in rows:
        p24, p26 = f(r['gen2024_two_party_dem']), f(r['gov2026_two_party_dem'])
        ratio = float(r['gov2026_electors']) / float(r['gen2024_electors'])
        if p24 is None or p26 is None or not (0.15 < p24 < 0.85 and 0.15 < p26 < 0.85) or abs(ratio - 1) > 0.08:
            continue
        ys.append(lg(p26) - lg(p24))
        xs.append(x_scope[SCOPE[r['sido']]])
        gs.append(r['sido'])
        used.append(r['district_2024'])
    y26, x26, g26 = np.array(ys), np.array(xs), np.array(gs)
    fit26 = B.fit(y26, x26, g26)
    ci26, _ = B.profile_ci(y26, x26, g26, fit26, lo=-4, hi=5, step=0.05)
    fit26_c0 = B.fit(y26, x26, g26, fix_c=0.0)
    ci26_c0, _ = B.profile_ci(y26, x26, g26, fit26_c0, fix_c=0.0, lo=-4, hi=5, step=0.05)
    # pair 2020 -> 2024 as in the backtest
    r20, _, _, y20a, x20a, g20a, _ = B.run()
    m = B.robust_mask(r20)
    pairs = [(y20a[m], x20a[m], g20a[m]), (y26, x26, g26)]
    pooled = joint_fit(pairs)
    pooled_ci = joint_ci(pairs, pooled)
    pooled_c0 = joint_fit(pairs, fix_c0=True)
    pooled_c0_ci = joint_ci(pairs, pooled_c0, fix_c0=True)
    nat = {'frame_change_2024_to_2026_logit': x_scope['강원'],
           'district_mean_change_logit': float(y26.mean()),
           'frame_q_2024': F.FA.sigmoid(a24['logit'] + a24['turnout_shift']),
           'frame_q_2026_05': F.FA.sigmoid(a26['logit'] + a26['turnout_shift'])}
    # ---------- 2. turnout, actual
    t = {el: np.array([float(r[f'{el}_turnout']) for r in rows]) for el in ('gen2024', 'pres2025', 'gov2026')}
    p25 = np.array([float(r['pres2025_two_party_dem']) for r in rows])
    w = np.array([float(r['pres2025_electors']) for r in rows])
    honam = np.array([SCOPE[r['sido']] == '광주/전라' for r in rows])
    tk = np.array([SCOPE[r['sido']] == '대구/경북' for r in rows])

    def wslope(yv, xv, wv):
        xm, ym = np.average(xv, weights=wv), np.average(yv, weights=wv)
        return float(np.sum(wv * (xv - xm) * (yv - ym)) / np.sum(wv * (xv - xm) ** 2))
    drop = t['pres2025'] - t['gov2026']
    mid = ~honam & ~tk
    turnout = {
        'national': {el: float(sum(float(r[f'{el}_votes']) for r in rows) / sum(float(r[f'{el}_electors']) for r in rows))
                     for el in ('gen2024', 'pres2025', 'gov2026')},
        'drop_pres_to_local_pp_per_10pp_dem_share': {'all_254': 10 * wslope(drop, p25, w),
                                                     'excluding_honam_and_tk': 10 * wslope(drop[mid], p25[mid], w[mid])},
        'gen2024_minus_local_pp_per_10pp_dem_share': {'all_254': 10 * wslope(t['gen2024'] - t['gov2026'], p25, w),
                                                      'excluding_honam_and_tk': 10 * wslope((t['gen2024'] - t['gov2026'])[mid], p25[mid], w[mid])},
        'note': 'district-level association only (ecological); positive = Democratic-leaning districts lose more turnout in the lower-turnout election'}
    # ---------- 3. baseline restarted from June 2026
    cfg = F.load_json('config/forecast_v030.json')
    districts = read_baseline(ROOT / 'data/baseline_2024.csv')
    c_agg, c_dev = F.current_frames(cfg, cfg['frame_inputs']['aggregator']['wording_classes_main'])
    waves = TO.load()
    tp = TO.turnout_propensity(waves)
    lv_c, _ = TO.period_shift(waves, ['678'], cfg['as_of'], c_agg['config']['half_life_days'], tp['tau_partisan'], tp['tau_independent'])
    cur = {s: c_agg['logit'] + lv_c + c_dev.get(s, {'deviation_logit': 0.0})['deviation_logit'] for s in REGIONAL_SCOPE_MEMBERS}
    change26 = {s: cur[s] - c26[s] for s in REGIONAL_SCOPE_MEMBERS}
    sim = F.Simulator(districts, cfg['draws'], cfg['seed'], REGIONAL_SCOPE_MEMBERS)
    by_key = {(r['sido'], r['district_2024']): r for r in rows}
    p0 = []
    for d in sim.eligible:
        r = by_key[(d['region'], d['district_id'].split('-', 2)[2])]
        p0.append(float(r['gov2026_two_party_dem']))
    base24 = sim.p0.copy()
    sim.p0 = np.array(p0)
    s = F.sigmas(cfg)
    latest = max(p['fieldwork_end'] for p in c_agg['polls_used'])
    days = (date.fromisoformat(cfg['target_election_date']) - date.fromisoformat(latest)).days
    alphas = np.round(np.arange(0, 1.5001, 0.05), 4)
    maj, npend = cfg['majority']['district_majority'], len(sim.pending)
    pts, thr = F.curve(sim, alphas, change26, s, days, s['region'], s['district'], maj, npend)
    zero = sim.run(0.0, change26, 0, 0, 0)
    main = F.load_json('outputs/forecast_v030.json')
    out = {
        'schema_version': 'dong_panel_analysis_1',
        'alpha': {
            'pair_2024_to_2026_governor': {'n': len(used), 'groups': 'province (governor candidate effect)',
                                           'exclusions': 'no two-party 2024 vote, share outside (0.15, 0.85), elector ratio off by >8%',
                                           'national': nat, 'x_by_scope': x_scope,
                                           'fit_free_intercept': {**fit26, 'alpha_ci95': ci26},
                                           'fit_no_intercept': {**fit26_c0, 'alpha_ci95': ci26_c0}},
            'pooled_2020_2024_and_2024_2026': {'free_intercepts': {**pooled, 'alpha_ci95': pooled_ci},
                                                 'no_intercepts': {**pooled_c0, 'alpha_ci95': pooled_c0_ci}},
            'caveats': ['2026 outcome is a governor vote: candidate and incumbency effects sit at the province level',
                        '2026 frame item lacks the 정부 지원/견제 clause',
                        'alpha with free intercepts is identified by 6 survey regions only']},
        'turnout_actual': turnout,
        'baseline_2026': {
            'definition': 'district two-party Democratic share in the 2026 governor vote; frame change = current (LV) minus May 2026 (662-664, LV)',
            'frame_change_by_scope': change26,
            'dem_seats_at_alpha0_no_noise': int(zero['dem_seats'][0]), 'dem_seats_2024_actual_245': 161,
            'mean_logit_shift_2024_to_2026_baseline': float(np.mean(np.log(sim.p0 / (1 - sim.p0)) - np.log(base24 / (1 - base24)))),
            'majority_thresholds': thr,
            'curve': pts,
            'main_2024_baseline_thresholds': main['headline']['majority_thresholds_main']},
    }
    (ROOT / 'outputs' / 'dong_panel_analysis.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    a = out['alpha']
    print(json.dumps({'pair26': {'n': len(used), 'alpha': round(fit26['alpha'], 2), 'ci': ci26, 'c': round(fit26['c'], 3),
                                 'alpha_c0': round(fit26_c0['alpha'], 2), 'ci_c0': ci26_c0, 'sr': round(fit26['sigma_region'], 3), 'sd': round(fit26['sigma_district'], 3)},
                      'national': {k: round(v, 3) for k, v in nat.items()},
                      'pooled': {'alpha': round(pooled['alpha'], 2), 'ci': pooled_ci, 'alpha_c0': round(pooled_c0['alpha'], 2), 'ci_c0': pooled_c0_ci},
                      'turnout': turnout['national'], 'slopes': turnout['drop_pres_to_local_pp_per_10pp_dem_share'],
                      'slopes_gen': turnout['gen2024_minus_local_pp_per_10pp_dem_share'],
                      'base26': {'change': {k: round(v, 2) for k, v in change26.items()}, 'alpha0_seats': int(zero['dem_seats'][0]), 'thr': thr['dem_loses_majority_alpha_bounds'], 'con': thr['con_gains_majority_alpha_bounds'],
                                 'a0.5': [pts[10]['dem']['mean'], pts[10]['con']['mean']]}}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
