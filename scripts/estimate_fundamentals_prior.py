#!/usr/bin/env python3
"""Optional fundamentals prior: presidential approval + mid-term drift (v0.3.0).

VoteHub uses an approval-scaled 'out-party gains in midterms' prior whose weight falls to zero
at election day. Korean analogue, from primary Gallup tables only:

1. beta: slope of the national frame coordinate on presidential approval, both role-aligned to the
   Democratic direction, from the 7 surveys that carry both items (2020 x3, 2024 x3, 2026 x1).
2. Mid-term approval drift: for every past president with data, the change in logit approval share
   (approve/(approve+disapprove)) between the tenure quarter matching *now* and the tenure quarter of
   the target election (Gallup quarterly table 1988-2024).
3. Prior frame shift = beta * mean drift; prior sd = |beta| * sd drift. Because the remaining number
   of quarters shrinks to zero at election day, the prior's weight decays to zero automatically.
Party support is not used. This prior is OFF in the main result; it runs as a labelled scenario.
"""
from __future__ import annotations
import json, math
from datetime import date
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
QUARTER_DAYS = 365.25 / 4
CURRENT = {'president': '이재명', 'inauguration': '2025-06-04', 'governing_party': '더불어민주당',
           'inauguration_basis': '제21대 대통령 취임일(당선 즉시 임기 개시)'}


def lg(p):
    return math.log(p / (1 - p))


def tenure_q(day, inauguration):
    return int((date.fromisoformat(day) - date.fromisoformat(inauguration)).days // QUARTER_DAYS)


def main(as_of_fieldwork='2026-10-15', election='2028-04-12'):
    g = json.loads((ROOT / 'data/history_polls/gallup_series_v030.json').read_text(encoding='utf-8'))
    # 1. frame vs approval, role-aligned
    frames = {}
    for f in sorted((ROOT / 'data/history_polls').glob('gallup_*_frame_observations.json')):
        for p in json.loads(f.read_text(encoding='utf-8'))['polls']:
            if p['scope'] == 'national':
                frames['gallup_' + f.name.split('_')[1]] = p
    pairs = []
    for sid, a in g['weekly_approval_paired'].items():
        if sid == 'gallup_678':
            pol = json.loads((ROOT / 'data/polls.json').read_text(encoding='utf-8'))
            fr = next(p for p in pol['polls'] if p['poll_id'] == 'gallup_678_frame_national')
            dem_gov = True
        else:
            fr = frames[sid]
            dem_gov = fr['governing_party'] == '더불어민주당'
        s, c = fr['shares']['정부지원'], fr['shares']['정부견제']
        qf = (s if dem_gov else c) / (s + c)
        qa = (a['approve'] if dem_gov else a['disapprove']) / (a['approve'] + a['disapprove'])
        pairs.append({'survey': sid, 'fieldwork_end': a['fieldwork_end'], 'democrats_governing': dem_gov,
                      'frame_logit': lg(qf), 'approval_logit_dem_direction': lg(qa)})
    X = np.array([[1, p['approval_logit_dem_direction']] for p in pairs])
    Y = np.array([p['frame_logit'] for p in pairs])
    coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ coef
    se = math.sqrt(float(resid @ resid) / (len(Y) - 2) / float(((X[:, 1] - X[:, 1].mean()) ** 2).sum()))
    beta = float(coef[1])
    # 2. mid-term approval drift by tenure quarter
    q_now = tenure_q(as_of_fieldwork, CURRENT['inauguration'])
    q_el = tenure_q(election, CURRENT['inauguration'])
    drifts = []
    for name, row in g['quarterly_approval_tenure']['rows'].items():
        ap, dp = row['approve'], row['disapprove']
        if max(q_now, q_el) >= len(ap) or None in (ap[q_now], ap[q_el], dp[q_now], dp[q_el]):
            continue
        a0 = ap[q_now] / (ap[q_now] + dp[q_now])
        a1 = ap[q_el] / (ap[q_el] + dp[q_el])
        drifts.append({'president': name, 'quarter_now_1based': q_now + 1, 'quarter_election_1based': q_el + 1,
                       'approve_share_now': a0, 'approve_share_election': a1, 'logit_change': lg(a1) - lg(a0)})
    dv = np.array([x['logit_change'] for x in drifts])
    mean_d, sd_d = float(dv.mean()), float(dv.std(ddof=1))
    # Democrats govern now: an approval fall is a fall of the Democratic-direction coordinate.
    shift = beta * mean_d
    out = {'schema_version': 'fundamentals_prior_1', 'status': 'optional_scenario_only_not_main_result',
           'party_support_used': False, 'current': CURRENT,
           'frame_on_approval': {'pairs': pairs, 'intercept': float(coef[0]), 'beta': beta, 'beta_se': se,
                                 'note': '7 paired surveys; levels regression pooled across eras'},
           'midterm_drift': {'tenure_quarter_now_1based': q_now + 1, 'tenure_quarter_election_1based': q_el + 1,
                             'presidents': drifts, 'mean_logit_change': mean_d, 'sd_logit_change': sd_d,
                             'source': 'Gallup quarterly tenure table in gallup_580_20240329.pdf'},
           'prior_frame_logit_shift_mean': shift, 'prior_frame_logit_shift_sd': abs(beta) * sd_d,
           'decay': 'shift computed over remaining tenure quarters; equals 0 when current quarter = election quarter',
           'limitations': ['7 presidents, heterogeneous eras; 1988-2011 quarterly medians.',
                           'beta from 7 surveys in 3 eras; level relation may not equal change relation.',
                           'Approval drift and frame drift overlap; scenario uses max of the two sds, not their sum.']}
    path = ROOT / 'outputs' / 'fundamentals_prior.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'beta': round(beta, 3), 'beta_se': round(se, 3), 'q_now': q_now + 1, 'q_el': q_el + 1,
                      'n_presidents': len(drifts), 'mean_drift': round(mean_d, 3), 'sd_drift': round(sd_d, 3),
                      'shift': round(shift, 3), 'shift_sd': round(abs(beta) * sd_d, 3)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
