#!/usr/bin/env python3
"""Government support/check frame aggregator (v0.3.0).

VoteHub-style national average of the *Democratic-direction coordinate*
q = D-component / (support + check), on the logit scale:

1. availability: only polls with published_at < as_of (date-only, same-day excluded)
2. recency: weight 0.5 ** (age_days / half_life), age from fieldwork_end
3. within-pollster averaging by recency; the pollster then carries the weight of its
   most recent release (repeated releases cannot dominate)
4. pollster quality weight (assumption table, documented in config)
5. house effects: leave-one-pollster-out residual vs. consensus of the *other* pollsters,
   shrunk toward 0 by n_j/(n_j + k_house); none without an overlapping other pollster
6. ENOP = sum of raw pollster weights (information content)

Regional deviations come only from Gallup regional tables relative to Gallup's own national
value in the same survey (same respondents), so no sample is counted twice.
Party support is never read.
"""
from __future__ import annotations
import math
from datetime import date

DEFAULTS = {
    'half_life_days': 28.0,
    'house_effect_shrinkage_k': 2.0,
    'house_effect_window_days': 45.0,
    'quality_weights': {'CATI_live_interview': 1.0, 'ARS_RDD': 0.5},
    'default_quality_weight': 0.5,
    'wording_classes': ['A_support_check'],
}


def logit(p):
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def d(s):
    return date.fromisoformat(s)


def dem_coordinate(poll, democratic_component):
    """democratic_component: 'support' when Democrats govern, 'check' when they oppose."""
    sh = poll['shares']
    s, c = sh.get('support'), sh.get('check')
    if s is None or c is None or s + c <= 0:
        raise ValueError(f"{poll.get('poll_id')}: support/check shares required")
    q = (s if democratic_component == 'support' else c) / (s + c)
    if not 0 < q < 1:
        raise ValueError(f"{poll.get('poll_id')}: coordinate undefined at 0/1")
    n = float(poll['sample_size']) * (s + c)
    return q, n


def available(polls, as_of):
    cut = d(as_of)
    return [p for p in polls if d(p['published_at']) < cut and d(p['fieldwork_end']) < cut]


def adaptive_half_life(polls, as_of, dense=14.0, sparse=28.0, window=28, min_polls=3):
    """VoteHub-style: fade faster when polling is dense, slower when sparse."""
    recent = [p for p in available(polls, as_of)
              if p.get('scope', 'national') == 'national' and (d(as_of) - d(p['fieldwork_end'])).days <= window]
    return dense if len(recent) >= min_polls else sparse


def _consensus(items, as_of, cfg, exclude=None, house=None):
    """items: list of dict(poll, L, n). Returns (C, enop, pollster_weights)."""
    hl = float(cfg['half_life_days'])
    groups = {}
    for it in items:
        j = it['poll']['pollster']
        if j == exclude:
            continue
        age = (d(as_of) - d(it['poll']['fieldwork_end'])).days
        r = 0.5 ** (age / hl)
        groups.setdefault(j, []).append((r, it))
    if not groups:
        return None, 0.0, {}
    num = den = 0.0
    wts = {}
    for j, lst in groups.items():
        rs = sum(r for r, _ in lst)
        Lj = sum(r * it['L'] for r, it in lst) / rs
        if house:
            Lj -= house.get(j, 0.0)
        mode = lst[0][1]['poll'].get('mode')
        qual = cfg['quality_weights'].get(mode, cfg['default_quality_weight'])
        w = max(r for r, _ in lst) * qual
        wts[j] = {'weight': w, 'recency_latest': max(r for r, _ in lst), 'quality': qual,
                  'pollster_logit': Lj, 'polls': [it['poll']['poll_id'] for _, it in lst]}
        num += w * Lj
        den += w
    return num / den, den, wts


def aggregate(polls, as_of, democratic_component, config=None):
    """Return national aggregate on the logit scale with diagnostics."""
    cfg = {**DEFAULTS, **(config or {})}
    if cfg.get('half_life_days') == 'adaptive':
        cfg['half_life_days'] = adaptive_half_life(
            [p for p in polls if p.get('wording_class', 'A_support_check') in cfg['wording_classes']], as_of)
    use = [p for p in available(polls, as_of)
           if p.get('scope', 'national') == 'national' and p.get('wording_class', 'A_support_check') in cfg['wording_classes']]
    if not use:
        raise ValueError('no available frame polls before as_of')
    items = []
    for p in use:
        q, n = dem_coordinate(p, democratic_component)
        items.append({'poll': p, 'q': q, 'L': logit(q), 'n': n,
                      'sampling_var': 1 / (n * q * (1 - q))})
    # house effects (leave-one-pollster-out, time-local, shrunk)
    house, house_diag = {}, {}
    pollsters = sorted({it['poll']['pollster'] for it in items})
    win = float(cfg['house_effect_window_days'])
    for j in pollsters:
        res = []
        for it in items:
            if it['poll']['pollster'] != j:
                continue
            t = it['poll']['fieldwork_end']
            local = [o for o in items if o['poll']['pollster'] != j
                     and abs((d(o['poll']['fieldwork_end']) - d(t)).days) <= win]
            if not local:
                continue
            C, _, _ = _consensus(local, t, cfg)
            res.append(it['L'] - C)
        k = float(cfg['house_effect_shrinkage_k'])
        h = sum(res) / (len(res) + k) if res else 0.0
        house[j] = h
        house_diag[j] = {'residuals_vs_others': res, 'n_overlapping': len(res), 'house_effect_logit': h}
    # identification: house effects are only relative; centre them so they average 0 over pollsters
    if len(pollsters) > 1:
        m = sum(house.values()) / len(house)
        for j in house:
            house[j] -= m
            house_diag[j]['house_effect_logit_centred'] = house[j]
    C, enop, wts = _consensus(items, as_of, cfg, house=house)
    # spread: weighted variance of pollster values around C plus mean sampling variance
    tot = sum(w['weight'] for w in wts.values())
    spread = sum(w['weight'] * (w['pollster_logit'] - C) ** 2 for w in wts.values()) / tot
    samp = sum(w['weight'] ** 2 * min(it['sampling_var'] for it in items if it['poll']['pollster'] == j)
               for j, w in wts.items()) / tot ** 2
    return {'as_of': as_of, 'democratic_component': democratic_component,
            'logit': C, 'q': sigmoid(C), 'enop': enop, 'spread_logit_sd': math.sqrt(spread),
            'sampling_sd_logit': math.sqrt(samp),
            'pollsters': wts, 'house_effects': house_diag,
            'polls_used': [{'poll_id': it['poll']['poll_id'], 'pollster': it['poll']['pollster'],
                            'fieldwork_end': it['poll']['fieldwork_end'], 'q': it['q'], 'logit': it['L'],
                            'wording_class': it['poll'].get('wording_class', 'A_support_check')} for it in items],
            'config': cfg}


def regional_deviations(national_polls, regional_polls, as_of, democratic_component, shrink_k, half_life_days=28.0):
    """Recency-averaged, shrunken Gallup regional deviation from Gallup national of the same survey.

    national_polls / regional_polls carry Gallup-style shares {'정부지원','정부견제'} converted by caller
    to {'support','check'}; regional polls must share fieldwork_end with a national poll (same sample).
    Returns {scope: {'deviation_logit', 'weight_sum', 'status'}}.
    """
    nat = {p['fieldwork_end']: p for p in available(national_polls, as_of)}
    out = {}
    by_scope = {}
    for p in available(regional_polls, as_of):
        by_scope.setdefault(p['scope'], []).append(p)
    for scope, lst in by_scope.items():
        num = den = 0.0
        used = []
        for p in lst:
            if p.get('suppressed') or not p.get('shares') or p['fieldwork_end'] not in nat:
                continue
            qn, _ = dem_coordinate(nat[p['fieldwork_end']], democratic_component)
            qr, _ = dem_coordinate(p, democratic_component)
            n = float(p['sample_size'])
            shrink = n / (n + shrink_k)
            age = (d(as_of) - d(p['fieldwork_end'])).days
            r = 0.5 ** (age / half_life_days)
            num += r * shrink * (logit(qr) - logit(qn))
            den += r
            used.append(p['poll_id'])
        if den:
            out[scope] = {'deviation_logit': num / den, 'status': 'observed_shrunken_recency_averaged', 'polls': used}
        else:
            out[scope] = {'deviation_logit': 0.0, 'status': 'national_fallback_regional_observation_unavailable', 'polls': []}
    return out


def gallup_to_generic(p):
    """Map Gallup archive/polls.json share labels to support/check without touching anything else."""
    sh = p.get('shares') or {}
    g = dict(p)
    g['shares'] = {} if not sh else {'support': sh.get('정부지원'), 'check': sh.get('정부견제')}
    g.setdefault('mode', 'CATI_live_interview')
    g.setdefault('wording_class', 'A_support_check')
    return g
