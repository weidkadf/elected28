#!/usr/bin/env python3
from __future__ import annotations
import csv, json, math
from datetime import date, timedelta
from pathlib import Path
from frame_aggregator import available

ROOT = Path(__file__).resolve().parent
GROUPS = ['dem', 'con', 'independent', 'residual_other_parties']


def logit(p):
    return math.log(p / (1 - p))


def load(path='data/history_polls/frame_party_crosstabs.json'):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))['waves']


PARTY_SUPPORT_CSV = 'data/nesdc/party_support_national.csv'
GROUP_COLUMNS = {'dem': ['더불어민주당'], 'con': ['국민의힘'], 'independent': ['지지정당 없음', '모름/ 무응답']}


def num(x):
    return float(x) if str(x).strip() else 0.0


def load_party_support(path=PARTY_SUPPORT_CSV):
    """Gallup Daily Opinion weekly party support (own surveys only), as turnout-group shares.

    Every weekly wave counts, including weeks with no 정부지원·견제 question. Gallup publishes the day after
    fieldwork ends, so published_at = fieldwork_end + 1 day (conservative: unknown hour, same-day cut excluded).
    """
    rows = []
    with (ROOT / path).open(encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if '갤럽' not in r['pollster'] or '자체' not in r['sponsor']:
                continue
            g = {k: sum(num(r[c]) for c in cols) for k, cols in GROUP_COLUMNS.items()}
            g['residual_other_parties'] = 100.0 - sum(g.values())
            if min(g.values()) < 0:
                raise ValueError(f'party support shares exceed 100: {r["reg_no"]}')
            end = date.fromisoformat(r['fieldwork_end'])
            rows.append({'reg_no': r['reg_no'], 'fieldwork_end': r['fieldwork_end'],
                         'published_at': (end + timedelta(days=1)).isoformat(),
                         'shares': {k: v / 100.0 for k, v in g.items()}})
    return rows


def party_composition(rows, as_of, half_life_days, window_days=28):
    """Recency-weighted turnout-group composition from weekly party support available before as_of."""
    cut = date.fromisoformat(as_of)
    used = [r for r in available(rows, as_of) if (cut - date.fromisoformat(r['fieldwork_end'])).days <= window_days]
    if not used:
        raise ValueError(f'no Gallup party-support waves within {window_days} days before {as_of}')
    acc = {g: 0.0 for g in GROUPS}; den = 0.0
    for r in used:
        w = 0.5 ** ((cut - date.fromisoformat(r['fieldwork_end'])).days / half_life_days)
        for g in GROUPS:
            acc[g] += w * r['shares'][g]
        den += w
    comp = {g: acc[g] / den for g in GROUPS}
    return {'shares': comp, 'reg_nos': [r['reg_no'] for r in used], 'window_days': window_days}


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


def lv_q(wave, tau_partisan, tau_independent, kappa=1.0, composition=None):
    """composition: optional {group: share}; replaces the wave's own crosstab group sizes."""
    fr = wave['frame_by_party']
    dem_gov = wave['governing_party'] == '더불어민주당'
    num = den = num0 = den0 = 0.0
    for g in GROUPS:
        x = fr[g]
        n = x['n_weighted'] if composition is None else composition[g]
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


def lv_shift(wave, tau_partisan, tau_independent, kappa=1.0, composition=None):
    q0, q1 = lv_q(wave, tau_partisan, tau_independent, kappa, composition)
    return logit(q1) - logit(q0)


def period_shift(waves, wave_ids, as_of, half_life_days, tau_partisan, tau_independent, kappa=1.0, composition=None):
    num = den = 0.0
    detail = {}
    for wave in available([dict(waves[w], wave_id=w) for w in wave_ids], as_of):
        age = (date.fromisoformat(as_of) - date.fromisoformat(wave['fieldwork_end'])).days
        r = 0.5 ** (age / half_life_days)
        s = lv_shift(wave, tau_partisan, tau_independent, kappa, composition)
        detail[wave['wave_id']] = {'shift_logit': s, 'recency_weight': r}
        num += r * s
        den += r
    if not detail:
        raise ValueError(f'no turnout waves available before {as_of}: {wave_ids}')
    return num / den, detail


def forecast_shifts(cfg, waves, baseline, current, tau_partisan, tau_independent, kappa, party_rows=None):
    ta = cfg['turnout_adjustment']
    pc = ta.get('party_composition') or {}
    periods = {'baseline': (ta['baseline_waves'], cfg['frame_inputs']['baseline_as_of'], baseline['config']['half_life_days']),
               'current': (ta['current_waves'], cfg['as_of'], current['config']['half_life_days'])}
    out, detail, comps = {}, {}, {}
    for key, (ids, as_of, hl) in periods.items():
        comp = None
        if pc.get('enabled'):
            rows = load_party_support() if party_rows is None else party_rows
            comp = party_composition(rows, as_of, hl, pc.get('window_days', 28))
        out[key], detail[key] = period_shift(waves, ids, as_of, hl, tau_partisan, tau_independent, kappa,
                                             None if comp is None else comp['shares'])
        if comp is not None:
            comps[key] = {'shares': {g: round(v, 4) for g, v in comp['shares'].items()}, 'gallup_reg_nos': comp['reg_nos']}
    if comps:
        detail['party_composition'] = comps
    return out['baseline'], out['current'], detail


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
