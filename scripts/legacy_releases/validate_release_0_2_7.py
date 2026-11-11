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
        assert json.loads(prior.read('election23/state.json'))['version'] == '0.2.6'
        protected = [n.removeprefix('election23/') for n in prior.namelist()
                     if not n.endswith('/') and (n.startswith('election23/data/') or n.startswith('election23/config/'))]
        protected += ['model.py', 'outputs/model_report.json', 'outputs/model_report_monthly.json',
                      'scripts/validate_historical_frames.py']
        for name in protected:
            assert (ROOT / name).read_bytes() == prior.read('election23/' + name), name
    checks = {'all_existing_data_config_engine_and_scenarios_immutable': True}
    for args, n in [(['test_model.py', 'test_safety_guards.py', 'test_boundary_inventory.py',
                     'test_ward_inventory.py', 'test_historical_frame_archive.py', 'test_historical_inventory.py',
                     'test_partial_identification.py'], 87),
                    (['discover', '-s', 'data/history_2020', '-p', 'test_crosscheck.py'], 8)]:
        test = subprocess.run([sys.executable, '-m', 'unittest', *args], cwd=ROOT, capture_output=True, text=True)
        assert test.returncode == 0 and f'Ran {n} tests' in test.stderr, test.stdout + test.stderr
    checks['all_95_tests_pass'] = True
    audit = json.loads((ROOT / 'outputs/model_audit_20261017_1348.json').read_text())
    assert audit['status'] == 'PASS' and all(audit['checks'].values())
    checks['independent_invariance_seed_scope_time_and_source_audit'] = True
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
    assert state['version'] == '0.2.7' and state['engine_version'] == '0.2.3'
    for name, digest in state['input_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    checks['254_current_district_rows_vote_and_seat_accounting'] = True
    result = {'project_version': '0.2.7', 'engine_version': '0.2.3', 'verified_date': '2026-10-17',
              'status': 'PASS', 'unit_tests_total': 95, 'checks': checks,
              'historical_diagnostic_districts': 253, 'geographic_crosswalk_eligible_districts': 0,
              'scenario_recalculated_for_release': False, 'scenario_numbers_changed': False,
              'diagnostic_is_forecast': False, 'partial_identification_geography_policy_complete': False,
              'remaining_gates': ['verified_geographic_ward_crosswalk', 'joint_geographic_remainder_constraints',
                                  'historical_baseline_availability', 'historical_candidate_party_mapping', 'time_split_calibration'],
              'protected_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in protected}}
    (ROOT / 'outputs/update_validation_20261017_1348.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'protected_sha256'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
