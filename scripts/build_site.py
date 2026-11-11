#!/usr/bin/env python3
"""Build the static dashboard data (docs/data.js) from model outputs. The page is docs/index.html."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
J = lambda p: json.loads((ROOT / p).read_text(encoding='utf-8'))


def main():
    f, a, r, st = J('outputs/forecast_v050.json'), J('outputs/alpha_identification.json'), J('outputs/pollster_ratings.json'), J('state.json')
    curve = [{'a': p['alpha'], 'd': p['dem']['mean'], 'dl': p['dem']['p10_p50_p90'][0], 'dh': p['dem']['p10_p50_p90'][2],
              'c': p['con']['mean'], 'cl': p['con']['p10_p50_p90'][0], 'ch': p['con']['p10_p50_p90'][2]} for p in f['scenarios']['main_composite_254']['curve']]
    t = f['headline']['thresholds_by_scenario']
    first = lambda d: list(d.values())[0]
    comb = a['combined']
    data = {
        'version': st['version'], 'as_of': f['as_of'], 'election': f['target_election_date'], 'days': f['headline']['days_to_election_from_latest_poll'],
        'curve': curve,
        'thresholds': {k: {'dem': first(v['dem_loses_majority_alpha']), 'con': first(v['con_gains_majority_alpha'])} for k, v in t.items() if k != 'sens_baseline_2024_only_245'},
        'alpha': {'grid': comb['grid'], 'w': [round(x, 5) for x in comb['weights_all_three']], 'w_ex': [round(x, 5) for x in comb['weights_all_three_excluding_presidential_pair']],
                  'post': comb['posteriors'], 'micro': {k: a['micro'][k] for k in ('n_polls', 'n_pollsters', 'mean_of_pollster_means', 'sd_between_pollsters', 'mean_conditional_vote')},
                  'pairs': {k: {x: v[x] for x in ('n_districts', 'alpha', 'ci95')} for k, v in a['regional']['pairs'].items()},
                  'joint': {k: a['regional']['joint_free_intercepts'][k] for k in ('alpha', 'ci95')}},
        'seats': {k: v for k, v in a['seat_distribution'].items() if k != 'condition'},
        'modes': r['mode_summary']['all_parsed'], 'quality': r['quality_weights_for_model'], 'n_rated': r['n_polls'],
        'frame_change': f['inputs']['frame_change_by_scope_main'], 'polls': f['inputs']['current_polls_A_plus_B'],
        'districts': [{'id': d['district_id'].split('-', 2)[2], 'r': d['region'], 'b24': d['dem_two_party_2024'], 'b25': d['dem_two_party_pres2025'], 'b': d['composite_baseline'],
                       'w': [d['dem_win_prob_alpha_0'], d['dem_win_prob_alpha_0.25'], d['dem_win_prob_alpha_0.5'], d['dem_win_prob_alpha_0.75'], d['dem_win_prob_alpha_1']]} for d in f['districts_main']],
    }
    (ROOT / 'docs/data.js').write_text('window.E23 = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    print(json.dumps({'docs/data.js': (ROOT / 'docs/data.js').stat().st_size, 'districts': len(data['districts'])}))


if __name__ == '__main__':
    main()
