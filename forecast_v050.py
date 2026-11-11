#!/usr/bin/env python3
"""Election23 v0.5.0: NESDC-rated poll aggregation + dong-based composite district baseline.

Reuses the v0.3 engine (alpha curve, sigma(d), turnout-adjusted frame change) and changes two inputs:
1. quality weights by survey mode come from outputs/pollster_ratings.json (NESDC 2025 presidential polls);
2. district baseline = composite partisan lean of gen2024 / pres2025 / gov2026 (dong-assigned results),
   pres2025 re-weighted to general-election turnout at dong level; all 254 districts simulated.
Still a conditional scenario engine: forecast_status=not_estimable (alpha is not identified).
"""
import argparse, csv, json, math
from collections import defaultdict
from datetime import date
from pathlib import Path
import numpy as np
import forecast_v030 as F
import turnout as TO

ROOT = Path(__file__).resolve().parent
lg = lambda p: math.log(p / (1 - p))
inv = lambda z: 1 / (1 + math.exp(-z))


def turnout_reweighted_pres(cfg):
    """district -> pres2025 two-party Dem share under general-election-like dong turnout."""
    lam = cfg['composite_baseline']['turnout_reweight']['lambda_toward_local']
    rows = list(csv.DictReader(open(ROOT / cfg['composite_baseline']['dong_panel'], encoding='utf-8')))
    pres, gov = {}, {}
    for r in rows:
        k = (r['district_2024'], r['sigungu'], r['dong'])
        e, v = float(r['electors'] or 0), float(r['votes'] or 0)
        if e <= 0 or v <= 0:
            continue
        if r['election'] == 'pres2025':
            a = pres.setdefault((r['sido'],) + k, [0, 0, 0, 0]); a[0] += e; a[1] += v; a[2] += float(r['dem']); a[3] += float(r['con'])
        elif r['election'] == 'gov2026':
            a = gov.setdefault(k, [0, 0]); a[0] += e; a[1] += v
    agg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0, 0])   # dem*, con*, dem raw, con raw, matched, total
    ratio_d = defaultdict(lambda: [0.0, 0.0])
    for (sido, dist, sgg, dong), (e, v, dm, cn) in pres.items():
        g = gov.get((dist, sgg, dong))
        if g:
            ratio_d[(sido, dist)][0] += g[1] / g[0] * e; ratio_d[(sido, dist)][1] += v
    for (sido, dist, sgg, dong), (e, v, dm, cn) in pres.items():
        t25 = v / e
        g = gov.get((dist, sgg, dong))
        rd = ratio_d[(sido, dist)]
        t26 = g[1] / g[0] if g else t25 * (rd[0] / rd[1] if rd[1] else 1.0)
        w = (t25 + lam * (t26 - t25)) / t25
        a = agg[(sido, dist)]
        a[0] += dm * w; a[1] += cn * w; a[2] += dm; a[3] += cn; a[4] += bool(g); a[5] += 1
    return {k: {'p': a[0] / (a[0] + a[1]), 'p_raw': a[2] / (a[2] + a[3]), 'matched': a[4] / a[5]} for k, a in agg.items() if a[0] + a[1] > 0}


def composite(cfg):
    cb = cfg['composite_baseline']
    P = list(csv.DictReader(open(ROOT / cb['panel'], encoding='utf-8')))
    tr = turnout_reweighted_pres(cfg) if cb['turnout_reweight']['enabled'] else {}
    f = lambda r, k: float(r[k]) if r.get(k) not in (None, '') else None
    nat = {}
    for e in ('gen2024', 'pres2025'):
        d = sum(f(r, e + '_dem') or 0 for r in P if f(r, e + '_two_party_dem') is not None and (f(r, e + '_con') or 0) > 0 and (f(r, e + '_dem') or 0) > 0)
        c = sum(f(r, e + '_con') or 0 for r in P if f(r, e + '_two_party_dem') is not None and (f(r, e + '_con') or 0) > 0 and (f(r, e + '_dem') or 0) > 0)
        nat[e] = d / (d + c)
    out = {}
    for r in P:
        k = (r['sido'], r['district_2024'])
        ok24 = (f(r, 'gen2024_dem') or 0) > 0 and (f(r, 'gen2024_con') or 0) > 0
        l24 = lg(f(r, 'gen2024_two_party_dem')) - lg(nat['gen2024']) if ok24 else None
        p25 = f(r, 'pres2025_two_party_dem')
        if p25 and k in tr:   # dong panel lacks out-of-district early votes, so apply only the reweighting difference
            p25 = inv(lg(p25) + lg(tr[k]['p']) - lg(tr[k]['p_raw']))
        l25 = lg(p25) - lg(nat['pres2025']) if p25 else None
        p26 = f(r, 'gov2026_two_party_dem')
        ok26 = p26 is not None and 0 < p26 < 1 and (f(r, 'gov2026_dem') or 0) > 0 and (f(r, 'gov2026_con') or 0) > 0
        out[k] = {'l24': l24, 'l25': l25, 'z26': lg(p26) if ok26 else None, 'p25_raw': f(r, 'pres2025_two_party_dem'), 'p25_tw': p25}
    by = defaultdict(list)
    for k, v in out.items():
        by[k[0]].append(v)
    w = cb['weights']
    for k, v in out.items():
        grp = [x for x in by[k[0]] if x['z26'] is not None]
        if v['z26'] is not None and grp:
            other = [np.mean([y for y in (x['l24'], x['l25']) if y is not None]) for x in grp]
            v['l26'] = v['z26'] - np.mean([x['z26'] for x in grp]) + float(np.mean(other))
        else:
            v['l26'] = None
        parts = [(w['gen2024'], v['l24']), (w['pres2025'], v['l25']), (w['gov2026'], v['l26'])]
        parts = [(a, b) for a, b in parts if b is not None]
        v['lean'] = sum(a * b for a, b in parts) / sum(a for a, _ in parts)
        v['p0'] = inv(v['lean'] + lg(nat['gen2024']))
        v['components'] = len(parts)
    return out, nat


class CompositeSimulator(F.Simulator):
    """All 254 districts; p0 replaced by the composite baseline (expressed in the 2024 national environment)."""

    def __init__(self, districts, draws, seed, scopes, comp):
        super().__init__(districts, draws, seed, scopes)
        rng = np.random.default_rng(seed + 50)
        rows, elig = [], []
        base = {d['district_id']: r for d, r in zip(self.eligible, self.rows)}
        for d in sorted(districts, key=lambda d: d['district_id']):
            c = comp[(d['region'], d['district_name'])]
            r = dict(base.get(d['district_id']) or {'tot': 1.0, 'max_other': 0.0, 'other_party': None,
                                                    'scope': F.PROVINCE_TO_SCOPE[d['region']], 'region': d['region'], 'p0': None})
            r['p0_2024'] = r['p0']; r['p0'] = c['p0']; r['formerly_pending'] = d['district_id'] not in base
            rows.append(r); elig.append(d)
        n_old = len(self.eligible)
        self.zd = np.vstack([self.zd, rng.standard_normal((len(rows) - n_old, self.draws))])
        order = [d['district_id'] for d in self.eligible] + [d['district_id'] for d in elig if d['district_id'] not in base]
        idx = {k: i for i, k in enumerate(order)}
        self.zd = self.zd[[idx[d['district_id']] for d in elig]]
        self.eligible, self.rows, self.pending = elig, rows, []
        self.p0 = np.array([r['p0'] for r in rows]); self.tot = np.array([r['tot'] for r in rows])
        self.mo = np.array([r['max_other'] for r in rows])
        self.scope_idx = np.array([self.scopes.index(r['scope']) for r in rows])


def frame_change(cfg, wording, quality=None):
    c2 = json.loads(json.dumps(cfg))
    if quality:
        c2['frame_inputs']['aggregator']['quality_weights'] = quality
    c2['frame_inputs']['aggregator'].pop('aggregator_sensitivity', None)
    b_agg, b_dev = F.baseline_frames(c2)
    c_agg, c_dev = F.current_frames(c2, wording)
    ta = cfg['turnout_adjustment']
    waves = TO.load(); tp = TO.turnout_propensity(waves)
    tauP = ta.get('tau_partisan') or tp['tau_partisan']; tauI = ta.get('tau_independent') or tp['tau_independent']
    bs, _ = TO.period_shift(waves, ta['baseline_waves'], cfg['frame_inputs']['baseline_as_of'], b_agg['config']['half_life_days'], tauP, tauI, ta['kappa_aligned_main'])
    cs, _ = TO.period_shift(waves, ta['current_waves'], cfg['as_of'], c_agg['config']['half_life_days'], tauP, tauI, ta['kappa_aligned_main'])
    return F.regional_change(b_agg, b_dev, c_agg, c_dev, bs, cs), c_agg


def validation(comp):
    """Does adding the pres2025 lean to the gen2024 lean improve the fit to gov2026 within-sido variation?"""
    rows = [v for v in comp.values() if None not in (v['l24'], v['l25'], v['l26'])]
    y = np.array([v['l26'] for v in rows]); a = np.array([v['l24'] for v in rows]); b = np.array([v['l25'] for v in rows])
    X = np.column_stack([a, b, np.ones(len(y))]); beta = np.linalg.lstsq(X, y, rcond=None)[0]
    rm = lambda e: float(np.sqrt(np.mean(e ** 2)))
    return {'n': len(y), 'ols_gov2026_lean_on': {'gen2024': round(float(beta[0]), 3), 'pres2025': round(float(beta[1]), 3)},
            'rmse_logit': {'gen2024_only': round(rm(y - a), 4), 'pres2025_only': round(rm(y - b), 4),
                           'mean_of_both': round(rm(y - (a + b) / 2), 4), 'ols': round(rm(y - X @ beta), 4)},
            'note': 'gov2026 lean already has sido means replaced, so this checks within-sido ordering only'}


def build(cfg, districts, draws=None, seed=None):
    draws = draws or cfg['draws']; seed = cfg['seed'] if seed is None else seed
    ac = cfg['alpha_curve']
    alphas = np.round(np.arange(ac['min'], ac['max'] + 1e-9, ac['step']), 4)
    s = F.sigmas(cfg)
    agg_cfg = cfg['frame_inputs']['aggregator']
    change, c_agg = frame_change(cfg, agg_cfg['wording_classes_main'])
    change_ab, c_agg_ab = frame_change(cfg, agg_cfg['wording_classes_sensitivity'])
    latest = max(p['fieldwork_end'] for p in c_agg['polls_used'])
    days = (date.fromisoformat(cfg['target_election_date']) - date.fromisoformat(latest)).days
    comp, nat = composite(cfg)
    maj = cfg['majority']['district_majority']
    sim = CompositeSimulator(districts, draws, seed, F.REGIONAL_SCOPE_MEMBERS, comp)
    old = F.Simulator(districts, draws, seed, F.REGIONAL_SCOPE_MEMBERS)
    scen = {}
    scen['main_composite_254'] = F.curve(sim, alphas, change, s, days, s['region'], s['district'], maj, 0)
    scen['sens_baseline_2024_only_245'] = F.curve(old, alphas, change, s, days, s['region'], s['district'], maj, len(old.pending))
    scen['sens_wording_A_plus_B'] = F.curve(sim, alphas, change_ab, s, days, s['region'], s['district'], maj, 0)
    for name, q in cfg['frame_inputs']['aggregator_sensitivity'].items():
        ch, _ = frame_change(cfg, agg_cfg['wording_classes_sensitivity'], q)
        scen[f'sens_wording_A_plus_B_quality_{name}'] = F.curve(sim, alphas, ch, s, days, s['region'], s['district'], maj, 0)
    cfg_nt = json.loads(json.dumps(cfg)); cfg_nt['composite_baseline']['turnout_reweight']['enabled'] = False
    comp_nt, _ = composite(cfg_nt)
    scen['sens_no_dong_turnout_reweight'] = F.curve(CompositeSimulator(districts, draws, seed, F.REGIONAL_SCOPE_MEMBERS, comp_nt), alphas, change, s, days, s['region'], s['district'], maj, 0)
    fp = F.load_json('outputs/fundamentals_prior.json')
    prior_sd = max(s['tau'] * math.sqrt(max(0, days - s['d_backtest'])), fp['prior_frame_logit_shift_sd'])
    scen['optional_fundamentals_prior'] = F.curve(sim, alphas, change, s, days, s['region'], s['district'], maj, 0, shift=fp['prior_frame_logit_shift_mean'], drift_override=prior_sd)
    sel = [0.0, 0.25, 0.5, 0.75, 1.0]
    res = {a: sim.run(a, change, F.sigma_national(a, days, s), s['region'], s['district']) for a in sel}
    dist = []
    for i, d in enumerate(sim.eligible):
        c = comp[(d['region'], d['district_name'])]; r = sim.rows[i]
        dist.append({'district_id': d['district_id'], 'region': d['region'], 'scope': r['scope'],
                     'dem_two_party_2024': None if r['p0_2024'] is None else round(r['p0_2024'], 4),
                     'dem_two_party_pres2025': None if c['p25_raw'] is None else round(c['p25_raw'], 4),
                     'dem_two_party_pres2025_turnout_reweighted': None if c['p25_tw'] is None else round(c['p25_tw'], 4),
                     'composite_baseline': round(c['p0'], 4), 'lean_components': c['components'], 'formerly_pending': r['formerly_pending'],
                     **{f'dem_win_prob_alpha_{a:g}': round(float(res[a]['dem_win_prob'][i]), 4) for a in sel}})
    thr = lambda k: scen[k][1]
    simple = lambda t: {'dem_loses_majority_alpha': t['dem_loses_majority_alpha_bounds'], 'con_gains_majority_alpha': t['con_gains_majority_alpha_bounds']}
    tw = [abs(c['p25_tw'] - c['p25_raw']) for c in comp.values() if c['p25_raw']]
    return {
        'schema_version': 'forecast_v050_1', 'engine_version': '0.5.0', 'forecast_status': 'not_estimable',
        'as_of': cfg['as_of'], 'target_election_date': cfg['target_election_date'],
        'headline': {'majority_thresholds_main': simple(thr('main_composite_254')), 'days_to_election_from_latest_poll': days,
                     'thresholds_by_scenario': {k: simple(v[1]) for k, v in scen.items()},
                     'seats_main_at_alpha': {f'{p["alpha"]:g}': {'dem_mean': p['dem']['mean'], 'con_mean': p['con']['mean']} for p in scen['main_composite_254'][0] if p['alpha'] in sel}},
        'inputs': {'frame_change_by_scope_main': change, 'frame_change_by_scope_A_plus_B': change_ab,
                   'current_polls_main': [p['poll_id'] for p in c_agg['polls_used']], 'current_polls_A_plus_B': [p['poll_id'] for p in c_agg_ab['polls_used']],
                   'quality_weights': agg_cfg['quality_weights'], 'pollster_ratings': 'outputs/pollster_ratings.json',
                   'national_two_party_dem': nat, 'composite_weights': cfg['composite_baseline']['weights'],
                   'dong_turnout_reweight_abs_change_pp': {'mean': round(100 * float(np.mean(tw)), 3), 'max': round(100 * float(np.max(tw)), 3)}},
        'validation_composite': validation(comp),
        'scenarios': {k: {'curve': v[0], 'thresholds': v[1]} for k, v in scen.items()},
        'districts_main': dist, 'config': cfg,
        'warning': 'conditional scenario; alpha not identified; 2024 boundaries; candidates unknown; PR seats not modelled'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', default='config/forecast_v050.json'); ap.add_argument('--baseline', default='data/baseline_2024.csv')
    ap.add_argument('--output', default='outputs/forecast_v050.json'); ap.add_argument('--draws', type=int); ap.add_argument('--seed', type=int)
    a = ap.parse_args()
    cfg = F.load_json(a.config)
    rep = build(cfg, F.read_baseline(ROOT / a.baseline), a.draws, a.seed)
    out = ROOT / a.output
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with open(out.with_name('alpha_curve_v050.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f); w.writerow(['scenario', 'alpha', 'sigma_national', 'dem_mean', 'dem_p10', 'dem_p50', 'dem_p90', 'con_mean', 'con_p10', 'con_p50', 'con_p90', 'other_mean'])
        for name, sc in rep['scenarios'].items():
            for p in sc['curve']:
                w.writerow([name, p['alpha'], p['sigma_national'], p['dem']['mean'], *p['dem']['p10_p50_p90'], p['con']['mean'], *p['con']['p10_p50_p90'], p['other']['mean']])
    with open(out.with_name('districts_v050.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rep['districts_main'][0].keys())); w.writeheader(); w.writerows(rep['districts_main'])
    print(json.dumps({'thresholds': rep['headline']['thresholds_by_scenario'], 'seats': rep['headline']['seats_main_at_alpha'],
                      'validation': rep['validation_composite'], 'change': rep['inputs']['frame_change_by_scope_main'],
                      'tw': rep['inputs']['dong_turnout_reweight_abs_change_pp']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
