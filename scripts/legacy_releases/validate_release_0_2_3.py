#!/usr/bin/env python3
"""Reproduce the guard-only engine release and compare every scenario number."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import build_report, read_baseline, VERSION


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    previous = Path(sys.argv[1]).resolve()
    districts = read_baseline(ROOT/'data/baseline_2024.csv')
    polls = json.loads((ROOT/'data/polls.json').read_text())
    configs = [json.loads((ROOT/f'config/{name}').read_text())
               for name in ['frame_comparison.json', 'frame_comparison_monthly.json']]
    checks = {}
    preserved = ['data/raw/nec_2024.csv', 'data/baseline_2024.csv', 'data/districts_2024.csv',
                 'data/polls.json', 'data/events.json', 'data/history_2020/nec_2020_raw.csv',
                 'data/history_2020/nec_2020_original_tables.zip',
                 'data/history_2020/verified_candidates_2020.csv']
    with zipfile.ZipFile(previous) as archive:
        for name in preserved:
            assert (ROOT/name).read_bytes() == archive.read('election23/'+name), name
        for cfg, name in zip(configs, ['model_report.json', 'model_report_monthly.json']):
            old = json.loads(archive.read('election23/outputs/'+name))
            new = build_report(districts, polls, cfg, draws=5000, seed=20261016)
            assert new['schema_version'] == VERSION == '0.2.3'
            assert new['coverage']['complete'] and new['coverage']['observed_districts'] == 254
            assert not new['scenario_failures'] and not new['frame_comparison_blockers']
            assert new['scenarios'] == old['scenarios'], 'Guard-only release changed scenario numbers'
            for scenario in new['scenarios']:
                assert len(scenario['districts']) == 254 and all(scenario['checks'].values())
                assert scenario['simulated_districts'] == 245 and scenario['not_estimable_districts'] == 9
                assert abs(sum(x['mean_seats'] for x in scenario['national_district_seats'].values()) - 245) < .01
            (ROOT/'outputs'/name).write_text(json.dumps(new, ensure_ascii=False, indent=2)+'\n')
            checks[name+'_all_scenario_values_unchanged'] = True
            if name == 'model_report.json':
                weekly = new
    checks['original_sources_and_2024_baseline_preserved'] = True
    assert sum(d['candidates'][0]['valid_votes'] for d in districts) == 29234129
    assert len(districts) == 254 and sum(len(d['candidates']) for d in districts) == 693
    checks['2024_baseline_254_districts_693_candidates_29234129_valid_votes'] = True
    assert weekly == build_report(districts, polls, configs[0], draws=5000, seed=20261016)
    checks['5000_draw_seed_reproducibility'] = True
    clean = copy.deepcopy(polls)
    clean['polls'] = [p for p in clean['polls'] if p.get('question_type') != 'party_support']
    assert weekly == build_report(districts, clean, configs[0], draws=5000, seed=20261016)
    checks['party_support_deleted_full_output_identical'] = True
    changed = copy.deepcopy(polls)
    for p in changed['polls']:
        if p.get('question_type') == 'party_support':
            p.update(shares={'더불어민주당': 999, '국민의힘': -900}, published_at='2099-99-99')
    assert weekly == build_report(districts, changed, configs[0], draws=5000, seed=20261016)
    checks['party_support_corrupted_full_output_identical'] = True
    for label, args, count in [('model_and_safety', ['test_model.py','test_safety_guards.py'], 29),
                               ('historical_crosscheck', ['discover','-s','data/history_2020','-p','test_crosscheck.py'], 8)]:
        result = subprocess.run([sys.executable,'-m','unittest',*args], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f'Ran {count} tests' in result.stderr
        checks[label+'_tests_pass'] = True
    manifest = json.loads((ROOT/'data/boundary_research/source_manifest.json').read_text())
    for source in manifest:
        p = ROOT/source['local_pdf']
        assert p.read_bytes().startswith(b'%PDF-') and digest(p) == source['sha256']
    assert {s['year'] for s in manifest} == {2020,2024}
    checks['official_boundary_source_pdf_hashes'] = True
    payload = {'project_version': VERSION, 'engine_version': VERSION, 'verified_date':'2026-10-16',
               'status':'PASS', 'checks':checks, 'unit_tests_total':37,
               'scenario_recalculated_for_release':True, 'scenario_numbers_changed':False,
               'draws':5000, 'seed':20261016, 'baseline_information':weekly['baseline_information'],
               'remaining_gates':['boundary_crosswalk_and_weights','historical_frame_poll_archive',
                                  'historical_availability_evidence_before_project_retrieval',
                                  'timestamp_precision','time_split_backtest_and_calibration'],
               'input_sha256':{n:digest(ROOT/n) for n in preserved + ['model.py','config/frame_comparison.json',
                               'config/frame_comparison_monthly.json','test_safety_guards.py']}}
    (ROOT/'outputs/update_validation_20261016_2137.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in payload.items() if k!='input_sha256'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
