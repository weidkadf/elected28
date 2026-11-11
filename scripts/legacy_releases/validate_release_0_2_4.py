#!/usr/bin/env python3
"""Verify a boundary-review-only release without recalculating predictions."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = {}
    protected = ['model.py','test_model.py','test_safety_guards.py','data/polls.json','data/events.json',
                 'data/raw/nec_2024.csv','data/baseline_2024.csv','data/districts_2024.csv',
                 'config/frame_comparison.json','config/frame_comparison_monthly.json',
                 'outputs/model_report.json','outputs/model_report_monthly.json',
                 'data/history_2020/nec_2020_raw.csv','data/history_2020/nec_2020_original_tables.zip',
                 'data/history_2020/verified_candidates_2020.csv',
                 'data/boundary_research/public_official_election_act_annex1_2020.pdf',
                 'data/boundary_research/public_official_election_act_annex1_2024.pdf']
    with zipfile.ZipFile(Path(sys.argv[1])) as prior:
        for name in protected:
            assert (ROOT/name).read_bytes() == prior.read('election23/'+name), name
    checks['original_baselines_engine_inputs_and_scenario_outputs_byte_identical'] = True
    for name in ['model_report.json','model_report_monthly.json']:
        report = json.loads((ROOT/'outputs'/name).read_text())
        assert report['schema_version']=='0.2.3' and report['coverage']['complete']
        for s in report['scenarios']:
            assert len(s['districts'])==254 and all(s['checks'].values())
            assert s['simulated_districts']==245 and s['not_estimable_districts']==9
            assert abs(sum(p['mean_seats'] for p in s['national_district_seats'].values())-245)<.01
    checks['all_254_current_scenarios_and_vote_seat_accounting'] = True
    for label, args, count in [('model_safety_boundary',['test_model.py','test_safety_guards.py','test_boundary_inventory.py'],39),
                              ('historical',['discover','-s','data/history_2020','-p','test_crosscheck.py'],8)]:
        r = subprocess.run([sys.executable,'-m','unittest',*args],cwd=ROOT,capture_output=True,text=True)
        assert r.returncode==0 and f'Ran {count} tests' in r.stderr, r.stdout+r.stderr
        checks[label+'_tests_pass'] = True
    audit = json.loads((ROOT/'outputs/model_audit_20261017_0250.json').read_text())
    assert audit['status']=='PASS' and all(audit['checks'].values())
    checks['separate_100_draw_party_exclusion_seed_and_accounting_audit'] = True
    independent = json.loads((ROOT/'outputs/boundary_case_audit_20261017_0250.json').read_text())
    assert independent['status']=='PASS'
    checks['independent_original_pdf_case_audit'] = True
    summary = json.loads((ROOT/'data/boundary_research/boundary_inventory_report.json').read_text())
    assert summary['extracted_counts']=={'2020':253,'2024':254}
    assert summary['parser_sha256']==hashlib.sha256((ROOT/'scripts/build_boundary_inventory.py').read_bytes()).hexdigest()
    assert summary['crosswalk_eligible_districts']==0 and not summary['vote_transfer_weights_estimated']
    text = (ROOT/'outputs/DISTRICT_STATUS.md').read_text()
    for label, count in [('정부지원·견제 연동(조건부·미보정)',245),('보류: 양당 후보 구도 확인 필요',9),
                         ('문구 동일·지리 미검증',171),('동일명칭·문구 차이',61),('동일명칭 전신 없음',22)]:
        assert text.count(label)==count,(label,text.count(label))
    checks['all_254_report_forecast_and_boundary_status_rows'] = True
    state = json.loads((ROOT/'state.json').read_text())
    for name, digest in state['input_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    checks['state_input_hashes_match'] = True
    result = {'project_version':'0.2.4','engine_version':'0.2.3','verified_date':'2026-10-17','status':'PASS',
              'unit_tests_total':47,'new_boundary_tests':10,'checks':checks,
              'scenario_recalculated_for_release':False,'scenario_numbers_changed':False,
              'boundary_review_counts':summary['comparison_status_counts'],
              'geographic_crosswalk_eligible_districts':0,
              'protected_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in protected},
              'boundary_parser_sha256':summary['parser_sha256'],
              'remaining_work':['administrative_boundary_history','geographic_vote_unit_crosswalk',
                                'historical_frame_poll_archive','time_split_backtest_and_calibration']}
    (ROOT/'outputs/update_validation_20261017_0250.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='protected_sha256'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
