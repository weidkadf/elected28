#!/usr/bin/env python3
"""Rough 300-seat view: 254 district seats (v0.5 engine) + 46 PR seats by parallel largest-remainder allocation.
PR shares start from the 2024 list vote and move with the same national frame shift (alpha x change + national error)."""
import json, sys, math
from datetime import date
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import forecast_v030 as F, forecast_v050 as V
PR2024 = {'민주연합': 26.69, '조국혁신당': 24.25, '국민의미래': 36.67, '개혁신당': 3.61}   # NEC official list vote %, parties over 3%
OTHER2024 = 100 - sum(PR2024.values())


def alloc(sh, seats=46):
    """sh: draws x parties (percent). 3% threshold, Hare largest remainder."""
    ok = sh >= 3.0; e = np.where(ok, sh, 0.0); q = e / e.sum(1, keepdims=True) * seats
    base = np.floor(q); rem = q - base; left = (seats - base.sum(1)).astype(int)
    order = np.argsort(-rem, axis=1)
    for i in range(sh.shape[1]):
        add = (left > i); base[np.arange(len(sh)), order[:, i]] += add
    return base


def main():
    cfg = F.load_json('config/forecast_v050.json'); s = F.sigmas(cfg)
    change, c_agg = V.frame_change(cfg, cfg['frame_inputs']['aggregator']['wording_classes_main'])
    days = (date.fromisoformat(cfg['target_election_date']) - date.fromisoformat(max(p['fieldwork_end'] for p in c_agg['polls_used']))).days
    comp, _ = V.composite(cfg)
    sim = V.CompositeSimulator(F.read_baseline(ROOT / 'data/baseline_2024.csv'), cfg['draws'], cfg['seed'], F.REGIONAL_SCOPE_MEMBERS, comp)
    w_scope = {}
    for r in sim.rows: w_scope[r['scope']] = w_scope.get(r['scope'], 0) + 1
    nat_change = sum(change[k] * v for k, v in w_scope.items()) / sum(w_scope.values())
    A = json.loads((ROOT / 'outputs/alpha_identification.json').read_text(encoding='utf-8'))['combined']
    grid = np.array(A['grid']); out = {'national_frame_change_logit': round(nat_change, 4), 'pr_rule': 'parallel, 46 seats, 3% threshold, largest remainder; Dem-bloc split 민주:조국 at 2024 ratio', 'scenarios': {}}
    d0 = PR2024['민주연합'] + PR2024['조국혁신당']; c0 = PR2024['국민의미래']; two = d0 + c0; z0 = math.log(d0 / c0); rj = PR2024['조국혁신당'] / d0

    def run(alphas, weights):
        acc = {k: [] for k in ('dem_d', 'con_d', 'oth_d', 'dem_pr', 'jk_pr', 'con_pr', 'ref_pr')}; ww = []
        for a, wi in zip(alphas, weights):
            sn = F.sigma_national(float(a), days, s); r = sim.run(float(a), change, sn, s['region'], s['district'])
            p = 1 / (1 + np.exp(-(z0 + a * nat_change + sn * sim.zn)))
            sh = np.column_stack([two * p * (1 - rj), two * p * rj, two * (1 - p), np.full_like(p, PR2024['개혁신당'])])
            al = alloc(sh)
            for k, v in zip(acc, (r['dem_seats'], r['con_seats'], r['other_seats'], al[:, 0], al[:, 1], al[:, 2], al[:, 3])): acc[k].append(v)
            ww.append(np.full(len(p), wi))
        X = {k: np.concatenate(v) for k, v in acc.items()}; w = np.concatenate(ww); w /= w.sum()
        m = lambda v: round(float((v * w).sum()), 1)
        def q(v, ps=(.1, .5, .9)):
            o = np.argsort(v); c = np.cumsum(w[o]); return [int(v[o][np.searchsorted(c, p)]) for p in ps]
        dem = X['dem_d'] + X['dem_pr']; bloc = dem + X['jk_pr']; con = X['con_d'] + X['con_pr']
        return {'district': {'민주': m(X['dem_d']), '국민의힘': m(X['con_d']), '기타': m(X['oth_d'])},
                'pr': {'민주': m(X['dem_pr']), '조국혁신당': m(X['jk_pr']), '국민의힘': m(X['con_pr']), '개혁신당': m(X['ref_pr'])},
                'total_300': {'민주': m(dem), '민주+조국혁신당': m(bloc), '국민의힘': m(con), '기타(지역구 제3후보+개혁신당 비례)': m(X['oth_d'] + X['ref_pr'])},
                'p10_p50_p90': {'민주': q(dem), '민주+조국혁신당': q(bloc), '국민의힘': q(con)},
                'p_majority_151': {'민주 단독': round(float(w[dem >= 151].sum()), 3), '민주+조국혁신당': round(float(w[bloc >= 151].sum()), 3), '국민의힘 단독': round(float(w[con >= 151].sum()), 3)}}
    for name, key in (('posterior_all_three', 'weights_all_three'), ('posterior_excluding_presidential_pair', 'weights_all_three_excluding_presidential_pair')):
        w = np.array(A[key]); keep = (w > 1e-4) & (grid >= 0); out['scenarios'][name] = run(grid[keep], w[keep])
    for a in (0.0, 0.2, 0.53, 0.75, 1.0):
        out['scenarios'][f'alpha_{a:g}'] = run([a], [1.0])
    (ROOT / 'outputs/seats_300.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for k, v in out['scenarios'].items():
        print(k, v['total_300'], v['pr'], v['p10_p50_p90'], v['p_majority_151'])
    print(out['national_frame_change_logit'])


if __name__ == '__main__':
    main()
