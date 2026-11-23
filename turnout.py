#!/usr/bin/env python3
from __future__ import annotations
import json, math
from datetime import date
from pathlib import Path
from frame_aggregator import available

ROOT = Path(__file__).resolve().parent
GROUPS = ['dem', 'con', 'independent', 'residual_other_parties']


def logit(p):
    return math.log(p / (1 - p))


def load(path='data/history_polls/frame_party_crosstabs.json'):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))['waves']


def turnout_propensity(waves, as_of):
    eligible = {key: wave for key, wave in waves.items() if wave.get('turnout_intention')}
    part, ind, used = [], [], []
    for w in available([dict(wave, wave_id=key) for key, wave in eligible.items()], as_of):
        t = w.get('turnout_intention')
        part += [t['dem']['certain_to_vote'], t['con']['certain_to_vote']]
        ind.append(t['independent']['certain_to_vote'])
        used.append(w['wave_id'])
    if not part:
        raise ValueError('no turnout-intention data')
    return {'tau_partisan': sum(part) / len(part), 'tau_independent': sum(ind) / len(ind),
            'waves_used': used}


def lv_q(wave, tau_partisan, tau_independent, kappa=1.0):
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
    num = den = 0.0
    detail = {}
    for wave in available([dict(waves[w], wave_id=w) for w in wave_ids], as_of):
        age = (date.fromisoformat(as_of) - date.fromisoformat(wave['fieldwork_end'])).days
        r = 0.5 ** (age / half_life_days)
        s = lv_shift(wave, tau_partisan, tau_independent, kappa)
        detail[wave['wave_id']] = {'shift_logit': s, 'recency_weight': r}
        num += r * s
        den += r
    if not detail:
        raise ValueError(f'no turnout waves available before {as_of}: {wave_ids}')
    return num / den, detail


def forecast_shifts(cfg, waves, baseline, current, tau_partisan, tau_independent, kappa):
    ta = cfg['turnout_adjustment']
    bs, bd = period_shift(waves, ta['baseline_waves'], cfg['frame_inputs']['baseline_as_of'],
                          baseline['config']['half_life_days'], tau_partisan, tau_independent, kappa)
    cs, cd = period_shift(waves, ta['current_waves'], cfg['as_of'],
                          current['config']['half_life_days'], tau_partisan, tau_independent, kappa)
    return bs, cs, {'baseline': bd, 'current': cd}


def main_shifts(cfg, baseline, current, waves=None):
    ta = cfg['turnout_adjustment']
    if not ta['enabled_in_main']:
        return 0.0, 0.0, {}
    waves = load() if waves is None else waves
    tau_partisan, tau_independent, _ = forecast_propensity(cfg, waves)
    return forecast_shifts(cfg, waves, baseline, current, tau_partisan, tau_independent, ta['kappa_aligned_main'])


def forecast_propensity(cfg, waves):
    ta = cfg['turnout_adjustment']
    tp = turnout_propensity(waves, cfg['frame_inputs']['baseline_as_of'])
    return (tp['tau_partisan'] if ta.get('tau_partisan') is None else ta['tau_partisan'],
            tp['tau_independent'] if ta.get('tau_independent') is None else ta['tau_independent'],
            tp['waves_used'])
