#!/usr/bin/env python3
"""Pollster / mode scorecard from NESDC-registered 2025 presidential polls (final two weeks).

Input : data/nesdc/pres2025_toplines.json  (parsed from NESDC result PDFs by scripts/parse_nesdc_pres.py)
Output: outputs/pollster_ratings.json
Error metric: logit two-party share  q = Lee/(Lee+Kim)  minus the official result.
Only the mode-level weights feed the model; pollster rows are provisional (small n, automatic parsing).
"""
import json, math, statistics as st
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ACTUAL = {'이재명': 49.42, '김문수': 41.15, '이준석': 8.34}   # NEC official, 2025-06-03
ALIAS = {'한국갤럽조사연구소': '한국갤럽', '(주)리서치뷰': '리서치뷰', '한길리서치': '한길리서치', '미디어토마토': '미디어토마토'}
MODE_KEY = {'CATI': 'CATI_live_interview', 'ARS': 'ARS_RDD'}
K_SHRINK = 3.0
lg = lambda p: math.log(p / (1 - p))


def summ(xs, aq):
    e = [lg(x['q']) - lg(aq) for x in xs]
    return {'n': len(xs), 'bias_logit': round(st.mean(e), 4), 'rmse_logit': round(math.sqrt(st.mean([a * a for a in e])), 4),
            'margin_error_pp': round(st.mean([x['lee'] - x['kim'] for x in xs]) - (ACTUAL['이재명'] - ACTUAL['김문수']), 2)}


def main():
    R = json.loads((ROOT / 'data/nesdc/pres2025_toplines.json').read_text(encoding='utf-8'))
    aq = ACTUAL['이재명'] / (ACTUAL['이재명'] + ACTUAL['김문수'])
    modes = {}
    for label, sel in [('all_parsed', R), ('question_verified_only', [x for x in R if x['score'] >= 1]),
                       ('final_week_from_0523', [x for x in R if x['end'] >= '2025-05-23'])]:
        modes[label] = {m: summ([x for x in sel if x['mode'] == m], aq) for m in ('CATI', 'ARS') if any(x['mode'] == m for x in sel)}
    base = modes['all_parsed']
    best = min(v['rmse_logit'] for v in base.values())
    qw = {MODE_KEY[m]: round((best / v['rmse_logit']) ** 2, 3) for m, v in base.items()}
    by = defaultdict(list)
    for x in R:
        by[(x['org'], x['mode'])].append(x)
    pol = []
    for (org, m), xs in by.items():
        s = summ(xs, aq)
        mm = base.get(m, {'rmse_logit': max(v['rmse_logit'] for v in base.values())})['rmse_logit'] ** 2
        mse = (s['n'] * s['rmse_logit'] ** 2 + K_SHRINK * mm) / (s['n'] + K_SHRINK)
        pol.append({'pollster': org, 'alias': ALIAS.get(org), 'mode': m, **s, 'rmse_shrunk': round(math.sqrt(mse), 4),
                    'weight_provisional': round(min(1.0, best ** 2 / mse), 3),
                    'question_verified_share': round(sum(x['score'] >= 1 for x in xs) / len(xs), 2)})
    pol.sort(key=lambda p: p['rmse_shrunk'])
    out = {'schema_version': 'pollster_ratings_v050_1', 'election': '제21대 대통령선거 2025-06-03', 'actual': ACTUAL,
           'window': 'fieldwork end 2025-05-13..05-27 (candidate registration to publication blackout)',
           'n_polls': len(R), 'metric': 'logit(Lee/(Lee+Kim)) minus official',
           'filters': 'automatic PDF parsing; dropped question score<0, Lee-Kim margin outside [-5,30], Lee Jun-seok>16 (parser/target mismatch), exact duplicates',
           'mode_summary': modes, 'quality_weights_for_model': qw,
           'quality_weights_rule': '(best mode RMSE / mode RMSE)^2 on all_parsed',
           'pollsters_provisional': pol,
           'caveats': ['one election only', 'presidential vote question, not the government-frame item the model aggregates',
                       'CATI has more undecided respondents; two-party normalisation assumes they split like deciders',
                       'pollster rows are not used by the model until toplines are hand-verified']}
    (ROOT / 'outputs/pollster_ratings.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'modes': modes, 'quality_weights': qw}, ensure_ascii=False))


if __name__ == '__main__':
    main()
