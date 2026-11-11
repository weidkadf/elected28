#!/usr/bin/env python3
"""Fail-closed release validation for historical archive tooling, not model fitting."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    protected = ['model.py', 'data/polls.json', 'data/events.json', 'data/baseline_2024.csv',
                 'data/districts_2024.csv', 'data/raw/nec_2024.csv', 'config/frame_comparison.json',
                 'config/frame_comparison_monthly.json', 'outputs/model_report.json',
                 'outputs/model_report_monthly.json', 'data/history_2020/nec_2020_raw.csv',
                 'data/history_2020/nec_2020_original_tables.zip',
                 'data/history_2020/verified_candidates_2020.csv']
    with zipfile.ZipFile(sys.argv[1]) as prior:
        assert prior.testzip() is None
        assert json.loads(prior.read('election23/state.json'))['version'] == '0.2.5'
        # Preserve every historical raw source in addition to the live engine inputs.
        protected += [name.removeprefix('election23/') for name in prior.namelist()
                      if name.startswith('election23/data/') and name.endswith('.pdf')]
        for name in protected:
            assert (ROOT / name).read_bytes() == prior.read('election23/' + name), name
    checks = {'immutable_original_sources_engine_inputs_and_scenarios': True}
    commands = [(['test_model.py', 'test_safety_guards.py', 'test_boundary_inventory.py',
                  'test_ward_inventory.py', 'test_historical_frame_archive.py', 'test_historical_inventory.py'], 71),
                (['discover', '-s', 'data/history_2020', '-p', 'test_crosscheck.py'], 8)]
    for args, count in commands:
        result = subprocess.run([sys.executable, '-m', 'unittest', *args], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0 and f'Ran {count} tests' in result.stderr, result.stdout + result.stderr
    checks['all_79_tests_pass'] = True
    audit = json.loads((ROOT / 'outputs/model_audit_20261017_0917.json').read_text())
    assert audit['status'] == 'PASS' and all(audit['checks'].values())
    checks['independent_input_invariance_seed_accounting_and_integrity_audit'] = True
    subprocess.run([sys.executable, 'scripts/validate_historical_frames.py', '--as-of', '2026-10-17'], cwd=ROOT, check=True)
    archive = json.loads((ROOT / 'outputs/historical_frame_inventory.json').read_text())
    assert archive['status'] == 'PASS' and not archive['training_approved'] and not archive['current_model_linked']
    checks['historical_archive_integrity_dates_roles_scopes_and_no_training_approval'] = True
    state = json.loads((ROOT / 'state.json').read_text())
    assert state['version'] == '0.2.6' and state['engine_version'] == '0.2.3'
    assert state['historical_frame_wave_count'] == archive['wave_count']
    assert state['historical_frame_archive_observation_count'] == archive['observation_count']
    for name, digest in state['input_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    text = (ROOT / 'outputs/DISTRICT_STATUS.md').read_text()
    assert text.count('정부지원·견제 연동(조건부·미보정)') == 245
    assert text.count('보류: 양당 후보 구도 확인 필요') == 9
    for name in ('model_report.json', 'model_report_monthly.json'):
        report = json.loads((ROOT / 'outputs' / name).read_text())
        assert report['coverage']['complete'] and report['coverage']['observed_districts'] == 254
        for scenario in report['scenarios']:
            assert len(scenario['districts']) == 254 and all(scenario['checks'].values())
            assert scenario['simulated_districts'] == 245 and scenario['not_estimable_districts'] == 9
            assert abs(sum(v['mean_seats'] for v in scenario['national_district_seats'].values()) - 245) < .01
    checks['254_report_rows_and_model_vote_seat_accounting'] = True
    report = {'project_version': '0.2.6', 'engine_version': '0.2.3', 'verified_date': '2026-10-17',
              'status': 'PASS', 'unit_tests_total': 79, 'checks': checks,
              'scenario_recalculated_for_release': False, 'scenario_numbers_changed': False,
              'historical_frame_waves': archive['wave_count'],
              'historical_frame_observations': archive['observation_count'],
              'historical_current_input_linked': False, 'training_approved': False,
              'protected_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in protected}}
    (ROOT / 'outputs/update_validation_20261017_0917.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'protected_sha256'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
