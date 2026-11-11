#!/usr/bin/env python3
"""Estimate the random-walk drift of the national frame coordinate (v0.3.0).

Data: Gallup monthly/weekly '총선 결과 기대' trend for the 21st (2019-2020) and 22nd (2022-2024)
cycles (data/history_polls/gallup_series_v030.json). On the logit of the role-aligned
Democratic-direction coordinate L_t:

    L_t2 - L_t1 = eps_t2 - eps_t1 + w,   w ~ N(0, tau^2 * (t2 - t1)),  eps ~ N(0, v_t)

v_t = 1 / (n_decided q (1-q)) with n = 1000 (Gallup weekly nominal) times design effect.
tau^2 is estimated by pooled moments  sum(dL^2 - v1 - v2) / sum(dt)  and by ML; the larger
is kept for the forecast (conservative). Output feeds sigma(d) = a + b * d**nu, nu = 1/2,
b = alpha * tau, VoteHub-style form.
"""
from __future__ import annotations
import json, math
from datetime import date
from pathlib import Path
import numpy as np
from scipy.optimize import minimize_scalar

ROOT = Path(__file__).resolve().parents[1]
DEFF = 1.5   # assumed design effect for weighted CATI weekly samples (documented assumption)


def series():
    d = json.loads((ROOT / 'data/history_polls/gallup_series_v030.json').read_text(encoding='utf-8'))
    out = []
    for key in ['cycle_21', 'cycle_22']:
        cyc = d['frame_trend'][key]
        comp = cyc['democratic_component']
        pts = []
        for p in cyc['points']:
            s, c = p['support'], p['check']
            q = (s if comp == 'support' else c) / (s + c)
            n = 1000 * (s + c) / DEFF
            pts.append((date.fromisoformat(p['fieldwork_end']), math.log(q / (1 - q)), 1 / (n * q * (1 - q))))
        out.append((key, cyc['election_date'], pts))
    return out


def main():
    pairs = []
    for key, el, pts in series():
        for (t1, l1, v1), (t2, l2, v2) in zip(pts, pts[1:]):
            pairs.append({'cycle': key, 'from': t1.isoformat(), 'to': t2.isoformat(),
                          'dt': (t2 - t1).days, 'dL': l2 - l1, 'sampling_var_sum': v1 + v2})
    dt = np.array([p['dt'] for p in pairs], float)
    dl = np.array([p['dL'] for p in pairs])
    vs = np.array([p['sampling_var_sum'] for p in pairs])
    tau2_mom = max(0.0, float((dl ** 2 - vs).sum() / dt.sum()))

    def nll(lt2):
        var = vs + math.exp(lt2) * dt
        return 0.5 * float(np.sum(np.log(var) + dl ** 2 / var))
    res = minimize_scalar(nll, bounds=(-20, 0), method='bounded')
    tau2_ml = math.exp(res.x)
    tau2 = max(tau2_mom, tau2_ml)
    # excess variance check: are short-gap differences consistent with sampling noise alone?
    short = dt <= 14
    out = {'schema_version': 'frame_drift_1', 'design_effect_assumed': DEFF,
           'pairs': pairs, 'n_pairs': len(pairs),
           'tau2_per_day_moment': tau2_mom, 'tau2_per_day_ml': tau2_ml, 'tau_per_sqrt_day_used': math.sqrt(tau2),
           'short_gap_mean_sq_diff_vs_sampling': {'n': int(short.sum()),
                                                  'mean_dL2': float((dl[short] ** 2).mean()),
                                                  'mean_sampling_var_sum': float(vs[short].mean())},
           'implied_frame_sd_logit': {f'{d}_days': math.sqrt(tau2 * d) for d in [14, 90, 180, 365, 545]},
           'sigma_d_form': 'sigma_nat(d) = a + b * d**0.5 with a = national error at d~0, b = alpha * tau',
           'limitations': ['Two cycles of one pollster; months 2023-12..2024-01 and 2019-06..2020-01 gaps.',
                           'Random walk without mean reversion is conservative at long horizons.',
                           'Design effect 1.5 is an assumption; lower deff lowers sampling var and raises tau.']}
    path = ROOT / 'outputs' / 'frame_drift.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: out[k] for k in ['n_pairs', 'tau2_per_day_moment', 'tau2_per_day_ml', 'tau_per_sqrt_day_used',
                                          'implied_frame_sd_logit', 'short_gap_mean_sq_diff_vs_sampling']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
