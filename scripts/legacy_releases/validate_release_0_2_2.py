#!/usr/bin/env python3
"""Validate a data-only release against the materialized previous archive."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    previous = Path(sys.argv[1]).resolve()
    if previous == ROOT.parent / 'Election23_Model.zip' and not previous.exists():
        raise ValueError('Materialized prior archive required before packaging')
    checks = {}
    hashes = {}
    protected = ['model.py', 'test_model.py', 'data/polls.json', 'data/events.json',
                 'data/baseline_2024.csv', 'data/districts_2024.csv',
                 'data/raw/nec_2024.csv', 'config/frame_comparison.json',
                 'config/frame_comparison_monthly.json',
                 'outputs/model_report.json', 'outputs/model_report_monthly.json',
                 'data/history_2020/nec_2020_raw.csv',
                 'data/history_2020/nec_2020_original_tables.zip',
                 'data/history_2020/reconstructed_candidates_QUARANTINED.csv',
                 'data/history_2020/reconstructed_district_totals_QUARANTINED.csv']
    with zipfile.ZipFile(previous) as archive:
        for relative in protected:
            name = 'election23/' + relative
            current = (ROOT / relative).read_bytes()
            assert current == archive.read(name), f'Unexpected change: {relative}'
            hashes[relative] = hashlib.sha256(current).hexdigest()
    checks['raw_baseline_model_inputs_and_scenario_outputs_unchanged'] = True
    for file in ['outputs/model_report.json', 'outputs/model_report_monthly.json']:
        report = json.loads((ROOT / file).read_text())
        assert report['coverage']['complete'] and report['coverage']['observed_districts'] == 254
        assert not report['scenario_failures'] and not report['frame_comparison_blockers']
        for s in report['scenarios']:
            assert len(s['districts']) == 254 and all(s['checks'].values())
            assert s['simulated_districts'] == 245 and s['not_estimable_districts'] == 9
            assert abs(sum(p['mean_seats'] for p in s['national_district_seats'].values()) - 245) < .01
        checks[file + '_coverage_and_accounting'] = True
    historical = json.loads((ROOT / 'data/history_2020/independent_crosscheck_report.json').read_text())
    assert historical['status'] == 'PASS' and historical['districts_passed'] == 253
    assert historical['candidate_labels_checked'] == 1101 and not historical['model_eligible']
    assert historical['parser_sha256'] == hashlib.sha256((ROOT / 'data/history_2020/crosscheck_official_tables.py').read_bytes()).hexdigest()
    with (ROOT / 'data/history_2020/verified_candidates_2020.csv').open(encoding='utf-8-sig', newline='') as f:
        verified = list(csv.DictReader(f))
    assert len(verified) == 1101 and all(r['current_model_eligible'] == 'false' for r in verified)
    checks['historical_crosscheck_253_districts_1101_labels'] = True
    checks['historical_data_not_wired_to_current_model'] = True
    audit = json.loads((ROOT / 'outputs/model_audit_20261016_2053.json').read_text())
    assert all(audit['checks'].values())
    checks['separate_100_draw_model_audit_invariance_seed_accounting'] = True
    for label, args in [('model_13', ['test_model.py']),
                        ('historical_8', ['discover', '-s', 'data/history_2020', '-p', 'test_crosscheck.py'])]:
        proc = subprocess.run([sys.executable, '-m', 'unittest', *args], cwd=ROOT,
                              text=True, capture_output=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        checks[label + '_tests_pass'] = True
    state = json.loads((ROOT / 'state.json').read_text())
    for relative, digest in state['input_sha256'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    text = (ROOT / 'outputs/DISTRICT_STATUS.md').read_text()
    assert text.count('정부지원·견제 연동(조건부·미보정)') == 245
    assert text.count('보류: 양당 후보 구도 확인 필요') == 9
    assert '프로젝트: 0.2.2' in text
    checks['all_254_report_rows_and_input_hashes'] = True
    result = {'project_version': '0.2.2', 'engine_version': '0.2.1',
              'verified_date': '2026-10-16', 'status': 'PASS', 'checks': checks,
              'new_unit_tests': 8, 'existing_model_tests': 13,
              'scenario_recalculated_for_release': False,
              'scenario_numbers_changed': False, 'protected_sha256': hashes,
              'remaining_model_gaps': [f['code'] for f in audit['findings']],
              'historical_scope': '2020 original-boundary district candidate totals only'}
    (ROOT / 'outputs/update_validation_20261016_2053.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'protected_sha256'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
