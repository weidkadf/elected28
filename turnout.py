#!/usr/bin/env python3
"""Likely-voter (turnout) adjustment of the frame coordinate (v0.3.1).

User decision 2026-11-11: party support may be used. Here it defines the turnout groups only.

For one Gallup wave with frame-by-party cells (data/history_polls/frame_party_crosstabs.json):
    groups g = 민주 지지, 보수 주정당 지지, 무당층, 기타 정당(잔차)
    q_LV = sum_g n_g tau_g k_gD D_g / sum_g n_g tau_g (k_gD D_g + k_gR R_g)
D_g / R_g = share of the group in the Democratic / opposite direction of the frame item.
tau_g     = turnout propensity: partisans tau_P, independents tau_I (Gallup '꼭 투표' 2020, 394/395)
k         = kappa for the frame-aligned partisan cells (민주 지지 x 민주 방향, 보수 지지 x 보수 방향);
            1.0 = no extra weight beyond party turnout (main), >1 = sensitivity
shift = logit(q_LV) - logit(q_all). Applied to the national aggregate of the same period.
"""
from __future__ import annotations
import json, math
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUPS = ['dem', 'con', 'independent', 'residual_other_parties']


def logit(p):
    return math.log(p / (1 - p))


def load(path='data/history_polls/frame_party_crosstabs.json'):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))['waves']


def turnout_propensity(waves):
    """Mean '꼭 투표할 것이다' share: partisans (민주·보수) and independents, over waves that asked it."""
    part, ind = [], []
    for w in waves.values():
        t = w.get('turnout_intention')
        if not t:
            continue
        part += [t['dem']['certain_to_vote'], t['con']['certain_to_vote']]
        ind.append(t['independent']['certain_to_vote'])
    if not part:
        raise ValueError('no turnout-intention data')
    return {'tau_partisan': sum(part) / len(part), 'tau_independent': sum(ind) / len(ind),
            'waves_used': [k for k, w in waves.items() if w.get('turnout_intention')]}


def lv_q(wave, tau_partisan, tau_independent, kappa=1.0):
    """Return (q_all, q_lv) in the Democratic direction for one wave."""
    fr = wave['frame_by_party']
    dem_gov = wave['governing_party'] == '더불어민주당'
    num = den = num0 = den0 = 0.0
    for g in GROUPS:
        x = fr[g]
        n = x['n_weighted']
        s, c = x['support'], x['check']
        d_share, r_share = (s, c) if dem_gov else (c, s)
        tau = tau_independent if g == 'independent' else tau_partisan
        kd = kappa if g == 'dem' else 1.0
        kr = kappa if g == 'con' else 1.0
        num += n * tau * kd * d_share
        den += n * tau * (kd * d_share + kr * r_share)
        num0 += n * d_share
        den0 += n * (d_share + r_share)
    return num0 / den0, num / den


def lv_shift(wave, tau_partisan, tau_independent, kappa=1.0):
    q0, q1 = lv_q(wave, tau_partisan, tau_independent, kappa)
    return logit(q1) - logit(q0)


def period_shift(waves, wave_ids, as_of, half_life_days, tau_partisan, tau_independent, kappa=1.0):
    """Recency-weighted average shift over the Gallup waves of one period (same weights as the aggregator)."""
    num = den = 0.0
    detail = {}
    for w in wave_ids:
        wave = waves[w]
        age = (date.fromisoformat(as_of) - date.fromisoformat(wave['fieldwork_end'])).days
        r = 0.5 ** (age / half_life_days)
        s = lv_shift(wave, tau_partisan, tau_independent, kappa)
        detail[w] = {'shift_logit': s, 'recency_weight': r}
        num += r * s
        den += r
    return num / den, detail
