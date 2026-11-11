#!/usr/bin/env python3
"""Election23 engine v0.3.0 -- alpha curve, aggregated frames, sigma(d), optional prior.

Keeps the v0.2.3 district mechanics of model.py (two-party logit swing with the two-party total
and third-party shares fixed at 2024; districts lacking both major parties are not estimable) and
changes what feeds them:

* frame inputs: recency/house-effect aggregate of comparable polls (frame_aggregator.py) instead of
  one survey per period; regional deviations from Gallup regional tables of the same surveys
* alpha: reported as a continuous curve, with the seat-majority alpha thresholds as the headline,
  because the partial 2020->2024 backtest does not identify alpha
* sigma: region/district scales from the backtest; national scale grows with days to election,
  sigma_nat(d) = a + alpha * tau * sqrt(d - d_bt)  (VoteHub-style a + b d^nu, nu = 1/2)
* optional fundamentals prior (approval mid-term drift) as a separate labelled scenario
Party support is never read. Output is NOT a calibrated forecast.
"""
from __future__ import annotations
import argparse, csv, json, math
from datetime import date
from pathlib import Path
import numpy as np

import frame_aggregator as FA
import turnout as TO
from model import DEM, CON, REGIONAL_SCOPE_MEMBERS, read_baseline, eligibility, validate_baseline_information

VERSION = '0.3.1'
ROOT = Path(__file__).resolve().parent
PROVINCE_TO_SCOPE = {m: s for s, ms in REGIONAL_SCOPE_MEMBERS.items() for m in ms}


def load_json(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


# ---------------------------------------------------------------- frame inputs
def baseline_frames(cfg, wording=None):
    fi = cfg['frame_inputs']
    nat, reg = [], []
    for w in fi['baseline_national_archive_waves']:
        for p in load_json(f'data/history_polls/gallup_{w}_frame_observations.json')['polls']:
            g = FA.gallup_to_generic(p)
            g['suppressed'] = not p['shares']
            (nat if p['scope'] == 'national' else reg).append(g)
    comp = cfg['roles']['baseline']['democratic_component']
    agg = FA.aggregate(nat, fi['baseline_as_of'], comp, {**fi['aggregator'], 'wording_classes': ['A_support_check']})
    dev = FA.regional_deviations(nat, reg, fi['baseline_as_of'], comp, fi['regional_shrinkage_k'], agg['config']['half_life_days'])
    return agg, dev


def current_frames(cfg, wording_classes):
    fi = cfg['frame_inputs']
    multi = load_json(fi['current_national_file'])['polls']
    comp = cfg['roles']['current']['democratic_component']
    agg = FA.aggregate(multi, cfg['as_of'], comp, {**fi['aggregator'], 'wording_classes': wording_classes})
    pol = load_json('data/polls.json')
    gall = [FA.gallup_to_generic(p) for p in pol['polls'] if p['question_type'] == 'government_frame'
            and p['poll_id'].startswith('gallup_6')]
    nat = [p for p in gall if p['scope'] == 'national']
    reg = [{**p, 'suppressed': bool(p.get('suppressed')) or not p['shares']} for p in gall if p['scope'] != 'national']
    dev = FA.regional_deviations(nat, reg, cfg['as_of'], comp, fi['regional_shrinkage_k'], agg['config']['half_life_days'])
    return agg, dev


def legacy_single_wave(cfg):
    """v0.2.3 inputs (Gallup 580 vs 678 only) through the same deviation code, for comparison."""
    comp_b, comp_c = cfg['roles']['baseline']['democratic_component'], cfg['roles']['current']['democratic_component']
    pol = load_json('data/polls.json')
    by = {p['poll_id']: FA.gallup_to_generic(p) for p in pol['polls'] if p['question_type'] == 'government_frame'}
    out = {}
    for period, prefix, comp, as_of in [('baseline', 'gallup_580_frame_', comp_b, '2024-04-10'),
                                       ('current', 'gallup_678_frame_', comp_c, cfg['as_of'])]:
        nat = by[prefix + 'national']
        qn, _ = FA.dem_coordinate(nat, comp)
        coords = {}
        for s in REGIONAL_SCOPE_MEMBERS:
            p = by.get(prefix + s)
            if p is None or p.get('suppressed') or not p['shares']:
                coords[s] = FA.logit(qn)
            else:
                qr, _ = FA.dem_coordinate(p, comp)
                w = p['sample_size'] / (p['sample_size'] + cfg['frame_inputs']['regional_shrinkage_k'])
                coords[s] = FA.logit(qn) + w * (FA.logit(qr) - FA.logit(qn))
        out[period] = coords
    return {s: out['current'][s] - out['baseline'][s] for s in REGIONAL_SCOPE_MEMBERS}


def regional_change(base_agg, base_dev, cur_agg, cur_dev, base_shift=0.0, cur_shift=0.0):
    """base_shift / cur_shift: national likely-voter shifts of each period (turnout.py)."""
    ch = {}
    for s in REGIONAL_SCOPE_MEMBERS:
        b = base_agg['logit'] + base_shift + base_dev.get(s, {'deviation_logit': 0.0})['deviation_logit']
        c = cur_agg['logit'] + cur_shift + cur_dev.get(s, {'deviation_logit': 0.0})['deviation_logit']
        ch[s] = c - b
    return ch


# ---------------------------------------------------------------- uncertainty
def sigmas(cfg):
    bt = load_json('outputs/backtest_2020_2024.json')['fit_intercept_free']
    dr = load_json('outputs/frame_drift.json')
    u = cfg['uncertainty']
    return {'region': bt['sigma_region'], 'district': bt['sigma_district'],
            'national_d0': u['sigma_national_at_d0']['value'], 'tau': dr['tau_per_sqrt_day_used'],
            'd_backtest': u['drift']['d_backtest_days']}


def sigma_national(alpha, days, s, drift_sd_override=None):
    extra = max(0.0, days - s['d_backtest'])
    drift = s['tau'] * math.sqrt(extra) if drift_sd_override is None else drift_sd_override
    return s['national_d0'] + alpha * drift


# ---------------------------------------------------------------- simulation
class Simulator:
    """Vectorised districts x draws simulator with common random numbers across alpha."""

    def __init__(self, districts, draws, seed, scopes):
        self.eligible = [d for d in sorted(districts, key=lambda d: d['district_id']) if eligibility(d)[0]]
        self.pending = [d for d in sorted(districts, key=lambda d: d['district_id']) if not eligibility(d)[0]]
        rng = np.random.default_rng(seed)
        self.scopes = sorted(scopes)
        self.zn = rng.standard_normal(draws)
        self.zr = {s: rng.standard_normal(draws) for s in self.scopes}
        self.zd = rng.standard_normal((len(self.eligible), draws))
        rows = []
        for d in self.eligible:
            cs = d['candidates']
            v = {c['party']: c['votes'] / c['valid_votes'] for c in cs}
            others = [(c['votes'] / c['valid_votes'], c['party']) for c in cs if c['party'] not in (DEM, CON)]
            mo = max(others) if others else (0.0, None)
            tot = v[DEM] + v[CON]
            rows.append({'p0': v[DEM] / tot, 'tot': tot, 'max_other': mo[0], 'other_party': mo[1],
                         'scope': PROVINCE_TO_SCOPE[d['region']], 'region': d['region']})
        self.rows = rows
        self.p0 = np.array([r['p0'] for r in rows])
        self.tot = np.array([r['tot'] for r in rows])
        self.mo = np.array([r['max_other'] for r in rows])
        self.scope_idx = np.array([self.scopes.index(r['scope']) for r in rows])
        self.draws = draws

    def run(self, alpha, change_by_scope, s_nat, s_reg, s_d, extra_national_shift=0.0):
        mean = np.array([alpha * (change_by_scope[r['scope']] + extra_national_shift) for r in self.rows])
        zr = np.stack([self.zr[s] for s in self.scopes])[self.scope_idx]
        z = np.log(self.p0 / (1 - self.p0))[:, None] + mean[:, None] + s_nat * self.zn[None, :] + s_reg * zr + s_d * self.zd
        p = 1 / (1 + np.exp(-z))
        dem = self.tot[:, None] * p
        con = self.tot[:, None] * (1 - p)
        mo = self.mo[:, None]
        dem_win = (dem > con) & (dem > mo)
        con_win = (con > dem) & (con > mo)
        return {'dem_seats': dem_win.sum(0), 'con_seats': con_win.sum(0),
                'other_seats': (~dem_win & ~con_win).sum(0), 'dem_win_prob': dem_win.mean(1),
                'con_win_prob': con_win.mean(1), 'dem_share_median': np.median(dem, 1)}


def summarize(arr):
    return {'mean': round(float(arr.mean()), 3),
            'p10_p50_p90': [int(v) for v in np.quantile(arr, [0.1, 0.5, 0.9], method='nearest')]}


def crossing(alphas, values, target, decreasing=True):
    """First alpha where the mean-seat curve falls below (or rises to) target, linear interpolation."""
    for i in range(1, len(alphas)):
        a0, a1, v0, v1 = alphas[i - 1], alphas[i], values[i - 1], values[i]
        if decreasing and v0 >= target > v1 or (not decreasing and v0 < target <= v1):
            return round(a0 + (a1 - a0) * (v0 - target) / (v0 - v1), 4)
    return None


def curve(sim, alphas, change, s, days, s_reg, s_d, majority, n_pending, shift=0.0, drift_override=None):
    pts = []
    for a in alphas:
        sn = sigma_national(a, days, s, drift_override)
        r = sim.run(a, change, sn, s_reg, s_d, shift)
        dm, cm = r['dem_seats'], r['con_seats']
        pts.append({'alpha': round(float(a), 4), 'sigma_national': round(sn, 4),
                    'dem': summarize(dm), 'con': summarize(cm), 'other': summarize(r['other_seats']),
                    'p_dem_majority_if_pending_all_dem': float((dm + n_pending >= majority).mean()),
                    'p_dem_majority_if_pending_none_dem': float((dm >= majority).mean()),
                    'p_con_majority_if_pending_all_con': float((cm + n_pending >= majority).mean()),
                    'p_con_majority_if_pending_none_con': float((cm >= majority).mean())})
    al = [p['alpha'] for p in pts]
    dmean = [p['dem']['mean'] for p in pts]
    cmean = [p['con']['mean'] for p in pts]
    thr = {
        'dem_loses_majority_alpha_bounds': {
            'pending_9_all_non_dem': crossing(al, dmean, majority, True),
            'pending_9_all_dem': crossing(al, dmean, majority - n_pending, True)},
        'con_gains_majority_alpha_bounds': {
            'pending_9_all_con': crossing(al, cmean, majority - n_pending, False),
            'pending_9_all_non_con': crossing(al, cmean, majority, False)},
        'definition': 'alpha at which the mean simulated seat curve crosses the 254-seat district majority (128); '
                      'two bounds because the 9 not-estimable seats are not allocated'}
    return pts, thr


def build(cfg, districts, draws=None, seed=None, alphas=None):
    draws = draws or cfg['draws']
    seed = cfg['seed'] if seed is None else seed
    ac = cfg['alpha_curve']
    alphas = alphas if alphas is not None else np.round(np.arange(ac['min'], ac['max'] + 1e-9, ac['step']), 4)
    poll_meta = {'as_of': cfg['as_of']}
    baseline_info = validate_baseline_information(districts, poll_meta, cfg)
    s = sigmas(cfg)
    b_agg, b_dev = baseline_frames(cfg)
    main_wc = cfg['frame_inputs']['aggregator']['wording_classes_main']
    sens_wc = cfg['frame_inputs']['aggregator']['wording_classes_sensitivity']
    c_agg, c_dev = current_frames(cfg, main_wc)
    c_agg_s, _ = current_frames(cfg, sens_wc)
    # likely-voter (turnout) adjustment, party-support groups (user decision 2026-11-11)
    ta = cfg['turnout_adjustment']
    waves = TO.load()
    tp = TO.turnout_propensity(waves)
    tauP = ta.get('tau_partisan') or tp['tau_partisan']
    tauI = ta.get('tau_independent') or tp['tau_independent']

    def shifts(kappa, ratio=None):
        ti = tauP * ratio if ratio is not None else tauI
        bs, bd = TO.period_shift(waves, ta['baseline_waves'], cfg['frame_inputs']['baseline_as_of'],
                                 b_agg['config']['half_life_days'], tauP, ti, kappa)
        cs, cd = TO.period_shift(waves, ta['current_waves'], cfg['as_of'],
                                 c_agg['config']['half_life_days'], tauP, ti, kappa)
        return bs, cs, {'baseline': bd, 'current': cd}
    k0 = ta['kappa_aligned_main']
    lv_b, lv_c, lv_detail = shifts(k0) if ta['enabled_in_main'] else (0.0, 0.0, {})
    change_raw = regional_change(b_agg, b_dev, c_agg, c_dev)
    change = regional_change(b_agg, b_dev, c_agg, c_dev, lv_b, lv_c)
    change_sens = regional_change(b_agg, b_dev, c_agg_s, c_dev, lv_b, lv_c)
    change_legacy = legacy_single_wave(cfg)
    sens_lv = {}
    for k in ta['sensitivity_kappa']:
        b, c, _ = shifts(k)
        sens_lv[f'sens_turnout_kappa_{k:g}'] = (regional_change(b_agg, b_dev, c_agg, c_dev, b, c), b, c)
    for r in ta['sensitivity_independent_ratio']:
        b, c, _ = shifts(k0, r)
        sens_lv[f'sens_turnout_independent_ratio_{r:g}'] = (regional_change(b_agg, b_dev, c_agg, c_dev, b, c), b, c)
    latest = max(p['fieldwork_end'] for p in c_agg['polls_used'])
    days = (date.fromisoformat(cfg['target_election_date']) - date.fromisoformat(latest)).days
    sim = Simulator(districts, draws, seed, REGIONAL_SCOPE_MEMBERS)
    maj, n_pending = cfg['majority']['district_majority'], len(sim.pending)
    scen = {}
    scen['main_aggregated_sigma_d'] = curve(sim, alphas, change, s, days, s['region'], s['district'], maj, n_pending)
    scen['sens_no_turnout_adjustment'] = curve(sim, alphas, change_raw, s, days, s['region'], s['district'], maj, n_pending)
    for name, (ch, _, _) in sens_lv.items():
        scen[name] = curve(sim, alphas, ch, s, days, s['region'], s['district'], maj, n_pending)
    scen['sens_wording_A_plus_B'] = curve(sim, alphas, change_sens, s, days, s['region'], s['district'], maj, n_pending)
    scen['sens_legacy_580_vs_678_inputs'] = curve(sim, alphas, change_legacy, s, days, s['region'], s['district'], maj, n_pending)
    scen['sens_no_time_drift'] = curve(sim, alphas, change, {**s, 'tau': 0.0}, days, s['region'], s['district'], maj, n_pending)
    fp = load_json('outputs/fundamentals_prior.json')
    prior_sd = max(s['tau'] * math.sqrt(max(0, days - s['d_backtest'])), fp['prior_frame_logit_shift_sd'])
    scen['optional_fundamentals_prior'] = curve(sim, alphas, change, s, days, s['region'], s['district'], maj, n_pending,
                                               shift=fp['prior_frame_logit_shift_mean'], drift_override=prior_sd)
    # district table for the main scenario at selected alphas
    sel = [0.0, 0.25, 0.5, 0.75, 1.0]
    dist_rows = []
    res = {a: sim.run(a, change, sigma_national(a, days, s), s['region'], s['district']) for a in sel}
    for i, d in enumerate(sim.eligible):
        dist_rows.append({'district_id': d['district_id'], 'region': d['region'], 'scope': sim.rows[i]['scope'],
                          'dem_two_party_2024': round(sim.rows[i]['p0'], 4),
                          **{f'dem_win_prob_alpha_{a:g}': round(float(res[a]['dem_win_prob'][i]), 4) for a in sel}})
    bt = load_json('outputs/backtest_2020_2024.json')
    main_pts, main_thr = scen['main_aggregated_sigma_d']
    return {
        'schema_version': VERSION, 'as_of': cfg['as_of'], 'target_election_date': cfg['target_election_date'],
        'forecast_status': 'not_estimable', 'model_status': 'alpha_curve_conditional_scenarios',
        'party_support_used': bool(ta['enabled_in_main']), 'party_support_scope': 'turnout weighting groups only',
        'baseline_information': baseline_info,
        'headline': {
            'primary_result': 'alpha curve + majority thresholds (alpha not identified by backtest)',
            'majority_thresholds_main': main_thr,
            'backtest_alpha': {'point': bt['fit_intercept_free']['alpha'], 'ci95': bt['fit_intercept_free']['alpha_profile_ci95'],
                               'identified': bt['alpha_identified']},
            'days_to_election_from_latest_poll': days},
        'frame_inputs': {
            'baseline_2024': {'national_q': b_agg['q'], 'national_logit': b_agg['logit'], 'enop': b_agg['enop'],
                              'half_life_days': b_agg['config']['half_life_days'], 'polls': b_agg['polls_used'],
                              'regional_deviation': {k: v['deviation_logit'] for k, v in b_dev.items()}},
            'current_main': {'national_q': c_agg['q'], 'national_logit': c_agg['logit'], 'enop': c_agg['enop'],
                             'half_life_days': c_agg['config']['half_life_days'], 'polls': c_agg['polls_used'],
                             'pollster_weights': c_agg['pollsters'], 'house_effects': c_agg['house_effects'],
                             'spread_logit_sd': c_agg['spread_logit_sd'],
                             'regional_deviation': {k: v['deviation_logit'] for k, v in c_dev.items()}},
            'current_sensitivity_A_plus_B': {'national_q': c_agg_s['q'], 'polls': c_agg_s['polls_used'],
                                             'house_effects': c_agg_s['house_effects']},
            'regional_logit_change_main': change, 'regional_logit_change_no_turnout_adjustment': change_raw, 'regional_logit_change_A_plus_B': change_sens,
            'regional_logit_change_legacy': change_legacy},
        'uncertainty': {**s, 'sigma_national_at_alpha': {f'{a:g}': round(sigma_national(a, days, s), 4) for a in [0, 0.5, 1]},
                        'form': cfg['uncertainty']['drift']['form']},
        'turnout_adjustment': {'enabled_in_main': ta['enabled_in_main'], 'tau_partisan': tauP, 'tau_independent': tauI,
                               'tau_source_waves': tp['waves_used'], 'kappa_aligned_main': k0,
                               'baseline_shift_logit': lv_b, 'current_shift_logit': lv_c,
                               'net_change_effect_logit': lv_c - lv_b, 'per_wave': lv_detail,
                               'sensitivity_shifts': {k: {'baseline': v[1], 'current': v[2]} for k, v in sens_lv.items()},
                               'party_support_use': 'turnout weighting groups only'},
        'fundamentals_prior': {'enabled_in_main': False, 'shift_mean': fp['prior_frame_logit_shift_mean'],
                               'shift_sd': fp['prior_frame_logit_shift_sd'], 'drift_sd_used': prior_sd},
        'coverage': {'simulated_districts': len(sim.eligible), 'not_estimable_districts': n_pending,
                     'not_estimable_ids': [d['district_id'] for d in sim.pending]},
        'scenarios': {k: {'curve': v[0], 'majority_thresholds': v[1]} for k, v in scen.items()},
        'districts_main': dist_rows,
        'draws': draws, 'seed': seed,
        'warnings': ['experimental_scenario_not_calibrated_forecast', 'alpha_not_identified_by_partial_backtest',
                     '2024_boundaries_and_candidates_fixed', 'party_support_used_for_turnout_weights_only',
                     'turnout_propensity_from_2020_self_report',
                     'non_gallup_inputs_secondary_press_reports', 'pr_seats_not_modelled'],
    }


def plot(report, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in font_manager.findSystemFonts():
        if 'NotoSansCJK' in f or 'NotoSansKR' in f:
            font_manager.fontManager.addfont(f)
    plt.rcParams['font.family'] = ['Noto Sans CJK KR', 'Noto Sans CJK JP', 'DejaVu Sans']
    sc = report['scenarios']
    fig, ax = plt.subplots(figsize=(9, 6.0), dpi=150)
    main = sc['main_aggregated_sigma_d']['curve']
    a = [p['alpha'] for p in main]
    ax.fill_between(a, [p['dem']['p10_p50_p90'][0] for p in main], [p['dem']['p10_p50_p90'][2] for p in main],
                    color='#2b6cb0', alpha=0.15, lw=0)
    ax.fill_between(a, [p['con']['p10_p50_p90'][0] for p in main], [p['con']['p10_p50_p90'][2] for p in main],
                    color='#c53030', alpha=0.15, lw=0)
    ax.plot(a, [p['dem']['mean'] for p in main], color='#2b6cb0', lw=2.2, label='더불어민주당 (주 시나리오, 평균·p10–p90)')
    ax.plot(a, [p['con']['mean'] for p in main], color='#c53030', lw=2.2, label='국민의힘 (주 시나리오)')
    pr = sc['optional_fundamentals_prior']['curve']
    ax.plot(a, [p['dem']['mean'] for p in pr], color='#2b6cb0', lw=1.2, ls='--', label='민주 — 펀더멘털 사전값 포함(선택)')
    ax.plot(a, [p['con']['mean'] for p in pr], color='#c53030', lw=1.2, ls='--', label='국힘 — 펀더멘털 사전값 포함(선택)')
    ax.axhline(128, color='#444', lw=1, ls=':')
    ax.axhline(119, color='#999', lw=0.8, ls=':')
    ax.text(1.48, 129.5, '254석 과반 128', ha='right', fontsize=8, color='#444')
    ax.text(1.48, 110, '보류 9석 전부 가산 시 기준 119', ha='right', fontsize=8, color='#888')
    ax.axvspan(0, 1, color='#000', alpha=0.03, lw=0)
    thr = sc['main_aggregated_sigma_d']['majority_thresholds']['dem_loses_majority_alpha_bounds']
    for k, v in thr.items():
        if v is not None:
            ax.axvline(v, color='#2b6cb0', lw=0.8, alpha=0.6)
    ax.set_xlabel('α (정부지원·견제 프레임 변화가 지역구 득표로 전이되는 비율)')
    ax.set_ylabel('모의 지역구 의석 (245곳 중)')
    ax.set_xlim(0, 1.5)
    ax.set_ylim(0, 245)
    ax.set_title('제23대 총선 지역구 α 곡선 — v0.3.0 (미보정 조건부 시나리오)', fontsize=11)
    ax.legend(fontsize=7.5, loc='upper center', bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False)
    bt = report['headline']['backtest_alpha']
    ax.text(0.01, 4, f"2020→2024 부분 백테스트 α={bt['point']:.2f}, 95% 구간 {bt['ci95'][0]:.1f}~{bt['ci95'][1]:.1f}: 식별 안 됨",
            fontsize=7.5, color='#555')
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', default='config/forecast_v030.json')
    ap.add_argument('--baseline', default='data/baseline_2024.csv')
    ap.add_argument('--output', default='outputs/forecast_v030.json')
    ap.add_argument('--draws', type=int)
    ap.add_argument('--seed', type=int)
    ap.add_argument('--no-plot', action='store_true')
    args = ap.parse_args()
    cfg = load_json(args.config)
    if cfg.get('comparison_type') != 'government_frame_v030':
        ap.error('config must declare comparison_type=government_frame_v030')
    rep = build(cfg, read_baseline(ROOT / args.baseline), args.draws, args.seed)
    out = ROOT / args.output
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with open(out.with_name('alpha_curve_v030.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['scenario', 'alpha', 'sigma_national', 'dem_mean', 'dem_p10', 'dem_p50', 'dem_p90',
                    'con_mean', 'con_p10', 'con_p50', 'con_p90', 'other_mean'])
        for name, sc in rep['scenarios'].items():
            for p in sc['curve']:
                w.writerow([name, p['alpha'], p['sigma_national'], p['dem']['mean'], *p['dem']['p10_p50_p90'],
                            p['con']['mean'], *p['con']['p10_p50_p90'], p['other']['mean']])
    with open(out.with_name('districts_v030.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rep['districts_main'][0].keys()))
        w.writeheader()
        w.writerows(rep['districts_main'])
    if not args.no_plot:
        plot(rep, out.with_name('alpha_curve_v030.png'))
    print(json.dumps({'output': args.output, 'thresholds': rep['headline']['majority_thresholds_main'],
                      'days': rep['headline']['days_to_election_from_latest_poll']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
