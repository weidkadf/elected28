#!/usr/bin/env python3
"""Validate diagnostic-only release and preserve prior sources/live scenarios."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with zipfile.ZipFile(sys.argv[1]) as prior:
        assert prior.testzip() is None
        assert json.loads(prior.read('election23/state.json'))['version'] == '0.2.8'
        protected = [n.removeprefix('election23/') for n in prior.namelist()
                     if not n.endswith('/') and (n.startswith('election23/data/') or n.startswith('election23/config/'))]
        protected += ['model.py', 'outputs/model_report.json', 'outputs/model_report_monthly.json',
                      'scripts/partial_identification.py', 'outputs/optional_remainder_diagnostic_253.json',
                      'scripts/validate_historical_frames.py', 'outputs/historical_frame_inventory.json']
        for name in protected:
            assert (ROOT / name).read_bytes() == prior.read('election23/' + name), name
    checks = {'all_existing_data_config_engine_and_scenarios_immutable': True}
    for args, n in [(['test_model.py', 'test_safety_guards.py', 'test_boundary_inventory.py',
                     'test_ward_inventory.py', 'test_historical_frame_archive.py', 'test_historical_inventory.py',
                     'test_partial_identification.py', 'test_historical_roles.py', 'test_backtest_readiness.py'], 115),
                    (['discover', '-s', 'data/history_2020', '-p', 'test_crosscheck.py'], 8)]:
        test = subprocess.run([sys.executable, '-m', 'unittest', *args], cwd=ROOT, capture_output=True, text=True)
        assert test.returncode == 0 and f'Ran {n} tests' in test.stderr, test.stdout + test.stderr
    checks['all_123_tests_pass'] = True
    import copy
    sys.path.insert(0, str(ROOT))
    from model import read_baseline, build_report
    districts = read_baseline(ROOT / 'data/baseline_2024.csv')
    polls = json.loads((ROOT / 'data/polls.json').read_text())
    config = json.loads((ROOT / 'config/frame_comparison.json').read_text())
    reference = build_report(districts, polls, config, draws=100, seed=20261016)
    assert reference == build_report(districts, polls, config, draws=100, seed=20261016)
    mutated = copy.deepcopy(polls)
    for row in mutated['polls']:
        if row.get('question_type') == 'party_support':
            row.clear()
            row.update(question_type='party_support', shares={'malformed': -99999})
    assert reference == build_report(districts, mutated, config, draws=100, seed=20261016)
    removed = copy.deepcopy(polls)
    removed['polls'] = [r for r in removed['polls'] if r.get('question_type') != 'party_support']
    assert reference == build_report(districts, removed, config, draws=100, seed=20261016)
    assert len(districts) == 254
    assert sum(len(d['candidates']) for d in districts) == 693
    for scenario in reference['scenarios']:
        assert all(scenario['checks'].values())
    checks['actual_100draw_party_input_mutation_deletion_seed_invariance'] = True
    from scripts.build_backtest_readiness import readiness_report
    ready = readiness_report()
    assert ready['fold_count'] == 5 and ready['executable_fold_count'] == 0
    assert not ready['backtest_executed'] and ready['performance_metrics'] is None
    assert ready == json.loads((ROOT / 'outputs/backtest_readiness.json').read_text())
    checks['five_readiness_manifests_are_blocked_not_scored_backtests'] = True
    subprocess.run([sys.executable, 'scripts/partial_identification.py'], cwd=ROOT, check=True)
    diagnostic = json.loads((ROOT / 'outputs/optional_remainder_diagnostic_253.json').read_text())
    assert diagnostic['status'] == 'PASS' and diagnostic['diagnostic_district_count'] == 253
    assert diagnostic['remainder_cap_valid_votes'] == 2800361
    assert not diagnostic['training_approved'] and not diagnostic['current_model_linked']
    assert not diagnostic['allocation_weights_created'] and not diagnostic['unknown_geography_solved']
    assert diagnostic['geographic_crosswalk_eligible_districts'] == 0
    assert sum(diagnostic['lead_status_counts'].values()) == 253
    assert diagnostic['code_sha256'] == hashlib.sha256((ROOT / 'scripts/partial_identification.py').read_bytes()).hexdigest()
    checks['253_original_unit_diagnostics_not_geographic_or_prediction_outputs'] = True
    subprocess.run([sys.executable, 'scripts/validate_historical_frames.py', '--as-of', '2026-10-17'], cwd=ROOT, check=True)
    inventory = json.loads((ROOT / 'outputs/historical_frame_inventory.json').read_text())
    assert inventory['wave_count'] == 4 and inventory['observation_count'] == 36
    assert inventory['target_election_coverage'] == [
        {'target_election_date': '2020-04-15', 'wave_count': 3, 'observation_count': 27, 'available_observations': 27},
        {'target_election_date': '2024-04-10', 'wave_count': 1, 'observation_count': 9, 'available_observations': 9}]
    assert not any(inventory[k] for k in ('party_support_used', 'training_approved', 'current_model_linked',
                                          'geography_approved', 'cross_election_pooling_approved',
                                          'party_successor_mapping_created', 'wave_pooling_or_weights_created'))
    archive = json.loads((ROOT / 'data/history_polls/gallup_578_frame_observations.json').read_text())
    for path_key, sha_key in [('source_file', 'source_sha256'), ('source_html_file', 'source_html_sha256')]:
        assert hashlib.sha256((ROOT / archive[path_key]).read_bytes()).hexdigest() == archive[sha_key]
    checks['historical_4_waves_36_rows_separate_role_profiles_not_training'] = True
    checks['new_578_pdf_and_html_integrity'] = True
    for name in ('model_report.json', 'model_report_monthly.json'):
        report = json.loads((ROOT / 'outputs' / name).read_text())
        assert report['coverage']['complete'] and report['coverage']['observed_districts'] == 254
        for scenario in report['scenarios']:
            assert len(scenario['districts']) == 254 and all(scenario['checks'].values())
            assert scenario['simulated_districts'] == 245 and scenario['not_estimable_districts'] == 9
            assert abs(sum(v['mean_seats'] for v in scenario['national_district_seats'].values()) - 245) < .01
    text = (ROOT / 'outputs/DISTRICT_STATUS.md').read_text()
    assert text.count('정부지원·견제 연동(조건부·미보정)') == 245 and text.count('보류: 양당 후보 구도 확인 필요') == 9
    state = json.loads((ROOT / 'state.json').read_text())
    assert state['version'] == '0.2.9' and state['engine_version'] == '0.2.3'
    for name, digest in state['input_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    checks['254_current_district_rows_vote_and_seat_accounting'] = True
    assert state['unit_test_count'] == 123 and state['historical_frame_wave_count'] == 4
    assert state['historical_frame_archive_observation_count'] == 36
    with zipfile.ZipFile(sys.argv[1]) as prior:
        for name in protected:
            assert (ROOT / name).read_bytes() == prior.read('election23/' + name), name
    checks['protected_files_still_identical_after_test_generators'] = True
    result = {'project_version': '0.2.9', 'engine_version': '0.2.3', 'verified_date': '2026-10-18',
              'status': 'PASS', 'unit_tests_total': 123, 'checks': checks,
              'historical_diagnostic_districts': 253, 'geographic_crosswalk_eligible_districts': 0,
              'scenario_recalculated_for_release': False, 'scenario_numbers_changed': False,
              'diagnostic_is_forecast': False, 'partial_identification_geography_policy_complete': False,
              'remaining_gates': ['verified_geographic_ward_crosswalk', 'joint_geographic_remainder_constraints',
                                  'historical_baseline_availability', 'historical_candidate_party_mapping', 'time_split_calibration'],
              'historical_archive_wave_count': 4, 'historical_archive_observations': 36,
              'new_source_sha256': {archive[k]: archive[v] for k, v in
                  [('source_file', 'source_sha256'), ('source_html_file', 'source_html_sha256')]},
              'historical_validator_sha256': hashlib.sha256((ROOT / 'scripts/validate_historical_frames.py').read_bytes()).hexdigest(),
              'protected_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in protected}}
    (ROOT / 'outputs/update_validation_20261018_0705.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'protected_sha256'}, ensure_ascii=False))


if __name__ == '__main__':
    main()


