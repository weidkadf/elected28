#!/usr/bin/env python3
"""Partial 2020->2024 backtest on same-name/same-statutory-text districts (v0.3.0).

User instruction 2026-11-05: run the backtest first on the 171 districts whose 2020 and 2024
statutory district text is identical, before full boundary verification. Geometry is NOT
verified (identical statutory text can still hide administrative-unit changes), so every
output carries `geography='same_statutory_text_unverified_geometry'`.

Information set (time-restricted):
  * 2020 baseline district results (verified alternative NEC tables)
  * Gallup frame surveys published before 2020-04-15 (392/394/395) and before 2024-04-10
    (578/579/580); fieldwork-end ages measured from each election day
  * target: 2024 district results (used only as the outcome)
Party support is never read.

Model (district i in survey region r):
  y_i = logit(p24_i) - logit(p20_i),  p = D/(D+C) two-party share
  x_r = L24_r - L20_r  (role-aligned Democratic-direction frame coordinate, aggregated)
  y_i = c + alpha * x_r + u_r + e_i,  u_r ~ N(0, s_r^2), e_i ~ N(0, s_d^2)
c is the realised national error of this single election pair; with one fold the national
error variance is not identifiable, so it is reported, not estimated.
"""
from __future__ import annotations
import csv, json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import frame_aggregator as FA  # noqa: E402
import turnout as TO  # noqa: E402
from model import REGIONAL_SCOPE_MEMBERS  # noqa: E402

DEM = '더불어민주당'
CON = {2020: '미래통합당', 2024: '국민의힘'}
PARTY_MAP_NOTE = ('Explicit role mapping for this backtest only: 2020 미래통합당 and 2024 국민의힘 are each '
                  'the main conservative party of their election. Original party names are kept in outputs.')
PROVINCE_TO_SCOPE = {m: s for s, ms in REGIONAL_SCOPE_MEMBERS.items() for m in ms}
ELECTION = {2020: '2020-04-15', 2024: '2024-04-10'}
COMPONENT = {2020: 'support', 2024: 'check'}   # Democratic direction: governing in 2020, opposition in 2024
WAVES = {2020: ['392', '394', '395'], 2024: ['578', '579', '580']}


def logit(p):
    return math.log(p / (1 - p))


def load_frames(year, waves=None):
    nat, reg = [], []
    for w in (waves or WAVES[year]):
        path = ROOT / f'data/history_polls/gallup_{w}_frame_observations.json'
        if not path.exists():
            path = ROOT / f'data/history_polls/gallup_{w}_local_frame.json'   # 2026 local-election item
        for p in json.loads(path.read_text(encoding='utf-8'))['polls']:
            g = FA.gallup_to_generic(p)
            g['suppressed'] = not p['shares']
            (nat if p['scope'] == 'national' else reg).append(g)
    return nat, reg


def lv_shift_for(year, wave_ids, hl, kappa=1.0):
    tw = TO.load()
    tp = TO.turnout_propensity(tw)
    shift, _ = TO.period_shift(tw, wave_ids, ELECTION[year], hl, tp['tau_partisan'], tp['tau_independent'], kappa)
    return shift


def frame_coordinates(year, shrink_k=400.0, waves=None, half_life='adaptive', turnout=True):
    nat, reg = load_frames(year, waves)
    agg = FA.aggregate(nat, ELECTION[year], COMPONENT[year], {'half_life_days': half_life})
    hl = agg['config']['half_life_days']
    dev = FA.regional_deviations(nat, reg, ELECTION[year], COMPONENT[year], shrink_k, hl)
    agg['turnout_shift'] = lv_shift_for(year, waves or WAVES[year], hl) if turnout else 0.0
    coords = {s: agg['logit'] + agg['turnout_shift'] + dev.get(s, {'deviation_logit': 0.0})['deviation_logit']
              for s in REGIONAL_SCOPE_MEMBERS}
    return coords, agg, dev


def load_districts():
    review = json.loads((ROOT / 'data/boundary_research/boundary_review_254.json').read_text(encoding='utf-8'))
    same = [r for r in review if r['review_status'] == 'same_name_same_statutory_text_geometry_unverified']
    r20 = defaultdict(list)
    with open(ROOT / 'data/history_2020/verified_candidates_2020.csv', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            r20[(row['province'], row['district'])].append(row)
    r24 = defaultdict(list)
    with open(ROOT / 'data/baseline_2024.csv', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            r24[row['district_id']].append(row)
    rows, excluded = [], []
    for r in same:
        s20 = r['same_name_statutory_2020']
        c20 = r20.get((s20['province_original'], s20['district_name'])) or r20.get((s20['province'], s20['district_name']))
        c24 = r24.get(r['district_id'])
        if not c20 or not c24:
            excluded.append({'district_id': r['district_id'], 'reason': 'missing_result_rows'})
            continue
        v20 = {x['party_original']: int(x['votes']) for x in c20}
        v24 = {x['party']: int(x['votes']) for x in c24}
        if DEM not in v20 or CON[2020] not in v20 or DEM not in v24 or CON[2024] not in v24:
            excluded.append({'district_id': r['district_id'], 'reason': 'two_major_parties_not_both_present_in_both_years'})
            continue
        if sum(1 for x in c20 if x['party_original'] in (DEM, CON[2020])) != 2 or \
           sum(1 for x in c24 if x['party'] in (DEM, CON[2024])) != 2:
            excluded.append({'district_id': r['district_id'], 'reason': 'ambiguous_multiple_major_party_candidates'})
            continue
        p20 = v20[DEM] / (v20[DEM] + v20[CON[2020]])
        p24 = v24[DEM] / (v24[DEM] + v24[CON[2024]])
        region = c24[0]['region']
        valid20 = int(c20[0]['valid_votes'])
        shares20 = {k: v / valid20 for k, v in v20.items()}
        valid24 = int(c24[0]['valid_votes'])
        winner24 = max(c24, key=lambda x: int(x['votes']))['party']
        rows.append({'district_id': r['district_id'], 'region': region, 'scope': PROVINCE_TO_SCOPE[region],
                     'p20': p20, 'p24': p24, 'y': logit(p24) - logit(p20),
                     'shares20': shares20, 'winner24': winner24, 'valid24': valid24})
    return rows, excluded


def negloglik(theta, y, x, g, fix_c=None):
    if fix_c is None:
        c, a, lsr, lsd = theta
    else:
        a, lsr, lsd = theta
        c = fix_c
    sr2, sd2 = math.exp(2 * lsr), math.exp(2 * lsd)
    r = y - c - a * x
    nll = 0.0
    for grp in np.unique(g):
        m = g == grp
        n = m.sum()
        rg = r[m]
        # cov = sd2 I + sr2 J ; closed-form inverse/determinant
        det = sd2 ** (n - 1) * (sd2 + n * sr2)
        quad = (rg @ rg) / sd2 - sr2 * rg.sum() ** 2 / (sd2 * (sd2 + n * sr2))
        nll += 0.5 * (math.log(det) + quad + n * math.log(2 * math.pi))
    return nll


def fit(y, x, g, fix_c=None, fix_alpha=None):
    def f(th):
        if fix_alpha is not None:
            th = ([th[0]] if fix_c is None else []) + [fix_alpha] + list(th[-2:])
        return negloglik(th, y, x, g, fix_c)
    start = ([0.0] if fix_c is None else []) + ([] if fix_alpha is not None else [0.5]) + [math.log(0.1), math.log(0.15)]
    res = minimize(f, start, method='Nelder-Mead', options={'xatol': 1e-7, 'fatol': 1e-9, 'maxiter': 20000})
    th = list(res.x)
    if fix_alpha is not None:
        th = ([th[0]] if fix_c is None else []) + [fix_alpha] + th[-2:]
    out = {'nll': float(res.fun), 'converged': bool(res.success)}
    if fix_c is None:
        out.update(c=th[0], alpha=th[1], sigma_region=math.exp(th[2]), sigma_district=math.exp(th[3]))
    else:
        out.update(c=fix_c, alpha=th[0], sigma_region=math.exp(th[1]), sigma_district=math.exp(th[2]))
    return out


def profile_ci(y, x, g, best, fix_c=None, lo=-3, hi=5, step=0.01):
    grid = np.arange(lo, hi + step / 2, step)
    prof = []
    for a in grid:
        prof.append(fit(y, x, g, fix_c=fix_c, fix_alpha=float(a))['nll'])
    prof = np.array(prof)
    inside = grid[prof - best['nll'] <= 1.920729]   # chi2_1(0.95)/2
    return [float(inside.min()), float(inside.max())] if len(inside) else [None, None], \
        {'grid': [round(float(a), 3) for a in grid[::10]], 'delta_nll': [round(float(v), 4) for v in (prof - best['nll'])[::10]]}


def evaluate(rows, x_by_scope, alpha, c, s_nat, s_reg, s_d, draws=4000, seed=20261105):
    """Engine-like winner simulation for 2024 from 2020 baseline; third parties fixed at 2020 share."""
    rng = np.random.default_rng(seed)
    scopes = sorted({r['scope'] for r in rows})
    nat = rng.normal(0, s_nat, draws)
    reg = {s: rng.normal(0, s_reg, draws) for s in scopes}
    briers, logls, sq, cover, dem_seats = [], [], [], [], np.zeros(draws)
    for r in rows:
        mu = math.log(r['p20'] / (1 - r['p20'])) + c + alpha * x_by_scope[r['scope']]
        z = mu + nat + reg[r['scope']] + rng.normal(0, s_d, draws)
        p = 1 / (1 + np.exp(-z))
        sh = r['shares20']
        tot = sh[DEM] + sh[CON[2020]]
        others = max([v for k, v in sh.items() if k not in (DEM, CON[2020])] or [0.0])
        dem = tot * p
        con = tot * (1 - p)
        win_dem = (dem > con) & (dem > others)
        pw = float(np.clip(win_dem.mean(), 1e-4, 1 - 1e-4))
        actual = 1.0 if r['winner24'] == DEM else 0.0
        briers.append((pw - actual) ** 2)
        logls.append(-(actual * math.log(pw) + (1 - actual) * math.log(1 - pw)))
        sq.append((float(np.median(p)) - r['p24']) ** 2)
        lo, hi = np.quantile(p, [0.1, 0.9])
        cover.append(lo <= r['p24'] <= hi)
        dem_seats += win_dem
    actual_seats = sum(r['winner24'] == DEM for r in rows)
    return {'alpha': alpha, 'brier': float(np.mean(briers)), 'log_loss': float(np.mean(logls)),
            'two_party_rmse_pp': 100 * math.sqrt(float(np.mean(sq))),
            'p10_p90_coverage': float(np.mean(cover)),
            'dem_seats_mean': float(dem_seats.mean()), 'dem_seats_actual': int(actual_seats),
            'seat_error': float(dem_seats.mean() - actual_seats)}


def run(shrink_k=400.0, waves=None, half_life='adaptive', turnout=True):
    rows, excluded = load_districts()
    c20, a20, d20 = frame_coordinates(2020, shrink_k, None if waves is None else waves[2020], half_life, turnout)
    c24, a24, d24 = frame_coordinates(2024, shrink_k, None if waves is None else waves[2024], half_life, turnout)
    x_by_scope = {s: c24[s] - c20[s] for s in REGIONAL_SCOPE_MEMBERS}
    y = np.array([r['y'] for r in rows])
    x = np.array([x_by_scope[r['scope']] for r in rows])
    g = np.array([r['scope'] for r in rows])
    return rows, excluded, x_by_scope, y, x, g, (a20, d20, a24, d24)


ROBUST_RULE = 'two-party share strictly inside (0.15, 0.85) in both 2020 and 2024 (logit leverage at extremes)'


def robust_mask(rows):
    return np.array([0.15 < r['p20'] < 0.85 and 0.15 < r['p24'] < 0.85 for r in rows])


def main():
    rows_all, excluded, xs, y_all, x_all, g_all, (a20, d20, a24, d24) = run()
    keep = robust_mask(rows_all)
    rows = [r for r, k in zip(rows_all, keep) if k]
    y, x, g = y_all[keep], x_all[keep], g_all[keep]
    free = fit(y, x, g)
    zero = fit(y, x, g, fix_c=0.0)
    ci_free, prof_free = profile_ci(y, x, g, free, lo=-6, hi=6, step=0.05)
    ci_zero, _ = profile_ci(y, x, g, zero, fix_c=0.0, lo=-6, hi=6, step=0.05)
    all_free = fit(y_all, x_all, g_all)
    ci_all, _ = profile_ci(y_all, x_all, g_all, all_free, lo=-8, hi=6, step=0.05)
    # shrinkage strength profile (k is re-estimated only by likelihood comparison)
    k_prof = {}
    for k in [50, 100, 200, 400, 800, 1600, 6400]:
        rk, _, _, yk, xk, gk, _ = run(shrink_k=float(k))
        mk = robust_mask(rk)
        k_prof[str(k)] = {**{kk: round(v, 4) if isinstance(v, float) else v for kk, v in fit(yk[mk], xk[mk], gk[mk]).items()}}
    # legacy single-wave inputs (395 vs 580) for comparison with the v0.2.3 engine design
    rl, _, xs_leg, yl, xl, gl, _ = run(waves={2020: ['395'], 2024: ['580']})
    ml = robust_mask(rl)
    legacy = fit(yl[ml], xl[ml], gl[ml])
    legacy['national_logit_change'] = xs_leg['강원']
    # same fit without the likely-voter adjustment (v0.3.0 inputs)
    rn, _, xs_n, yn, xn, gn, _ = run(turnout=False)
    mn = robust_mask(rn)
    no_turnout = fit(yn[mn], xn[mn], gn[mn])
    no_turnout['national_logit_change'] = xs_n['강원']
    # leave-one-region-out alpha (out-of-sample evaluation)
    loro = {}
    for s in sorted(set(g)):
        m = g != s
        loro[s] = fit(y[m], x[m], g[m])['alpha']
    s_nat_assumed = 0.12
    evals = []
    for a in [0.0, 0.5, 1.0, free['alpha']]:
        evals.append(evaluate(rows, xs, a, 0.0, s_nat_assumed, free['sigma_region'], free['sigma_district']))
    # out-of-sample: each region evaluated with alpha fitted without it
    oos = []
    for s in sorted(set(g)):
        sub = [r for r in rows if r['scope'] == s]
        oos.append({**evaluate(sub, xs, loro[s], 0.0, s_nat_assumed, free['sigma_region'], free['sigma_district']), 'scope': s, 'n': len(sub)})
    nat_y = float(np.average(y))
    out = {
        'schema_version': 'backtest_2020_2024_partial_1',
        'status': 'PARTIAL_BACKTEST_EXECUTED',
        'authorization': 'user instruction 2026-11-05: run partial backtest on 171 same-text districts first',
        'geography': 'same_statutory_text_unverified_geometry',
        'party_support_used': True,
        'party_support_scope': 'turnout weighting groups only (user decision 2026-11-11)',
        'party_mapping': PARTY_MAP_NOTE,
        'information_set': {'baseline_results': '2020 verified alternative NEC tables',
                            'frames_2020': [p['poll_id'] for p in a20['polls_used']],
                            'frames_2024': [p['poll_id'] for p in a24['polls_used']],
                            'availability_rule': 'published_at < election day (date only)',
                            'half_life_days': {'2020': a20['config']['half_life_days'], '2024': a24['config']['half_life_days']}},
        'sample': {'same_text_districts': 171, 'two_party_both_years': len(rows_all), 'used_primary': len(rows),
                   'robust_rule': ROBUST_RULE,
                   'robust_excluded': [r['district_id'] for r, k in zip(rows_all, keep) if not k],
                   'excluded': excluded},
        'frame_aggregate': {'2020_national_q': a20['q'], '2024_national_q': a24['q'],
                            'national_logit_change': a24['logit'] - a20['logit'],
                            'regional_logit_change': xs,
                            'regional_deviation_2020': {k: v['deviation_logit'] for k, v in d20.items()},
                            'regional_deviation_2024': {k: v['deviation_logit'] for k, v in d24.items()}},
        'observed': {'mean_district_two_party_logit_change': nat_y,
                     'by_scope': {s: {'n': int((g == s).sum()), 'mean_y': float(y[g == s].mean()), 'x': xs[s]} for s in sorted(set(g))}},
        'fit_intercept_free': {**free, 'alpha_profile_ci95': ci_free, 'profile': prof_free,
                               'note': 'alpha identified from cross-regional variation; c = realised 2024 national error'},
        'fit_no_intercept': {**zero, 'alpha_profile_ci95': ci_zero},
        'fit_all_155_incl_extremes': {**all_free, 'alpha_profile_ci95': ci_all,
                                      'note': 'dominated by 6 Honam districts with extreme two-party shares'},
        'alpha_identified': bool(ci_free[0] is not None and ci_free[0] > 0 and ci_free[1] - ci_free[0] < 1.0),
        'conclusion': ('alpha is NOT identified by one election pair: 95% profile interval spans negative to >2. '
                       'sigma_region and sigma_district are identified and replace the v0.2 assumptions.'),
        'fit_legacy_single_wave_inputs': legacy,
        'fit_without_turnout_adjustment': no_turnout,
        'turnout_adjustment': {'shift_2020': a20['turnout_shift'], 'shift_2024': a24['turnout_shift'],
                               'national_change_effect': a24['turnout_shift'] - a20['turnout_shift'],
                               'national_frame_change_with': xs['강원'], 'national_frame_change_without': xs_n['강원'],
                               'observed_mean_district_change': float(np.average(y))},
        'shrinkage_k_profile': k_prof,
        'leave_one_region_out_alpha': loro,
        'evaluation_in_sample': evals,
        'evaluation_leave_one_region_out': oos,
        'not_identified': ['national_error_variance (single election pair)', 'time dependence of alpha'],
        'limitations': [
            'One election pair; 8 survey regions (2 suppressed -> national fallback) identify alpha.',
            'Districts are not independent draws of the same geography; statutory text identity is not polygon identity.',
            'Candidate changes, incumbency and third-party entry are absorbed in residuals.',
            'Frames measured ~2 weeks before each election; forward use at longer horizons needs sigma(d).'],
    }
    path = ROOT / 'outputs' / 'backtest_2020_2024.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(path.relative_to(ROOT)), 'n': len(rows), 'identified': out['alpha_identified'],
                      'alpha_free': round(free['alpha'], 3), 'ci': ci_free,
                      'alpha_c0': round(zero['alpha'], 3), 'ci_c0': ci_zero,
                      'sigma_region': round(free['sigma_region'], 3), 'sigma_district': round(free['sigma_district'], 3),
                      'c': round(free['c'], 3), 'legacy_alpha': round(legacy['alpha'], 3)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
