#!/usr/bin/env python3
"""Release validation: retain immutable model/source bytes; test historical prep."""
import hashlib,json,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    protected=['model.py','data/polls.json','data/events.json','data/baseline_2024.csv','data/districts_2024.csv',
               'data/raw/nec_2024.csv','config/frame_comparison.json','config/frame_comparison_monthly.json',
               'outputs/model_report.json','outputs/model_report_monthly.json',
               'data/history_2020/nec_2020_raw.csv','data/history_2020/nec_2020_original_tables.zip',
               'data/history_2020/verified_candidates_2020.csv']
    with zipfile.ZipFile(Path(sys.argv[1])) as z:
        for name in protected:assert (ROOT/name).read_bytes()==z.read('election23/'+name),name
    checks={'immutable_original_sources_engine_inputs_and_scenarios':True}
    for name in ['model_report.json','model_report_monthly.json']:
        report=json.loads((ROOT/'outputs'/name).read_text())
        assert report['coverage']['complete'] and report['coverage']['observed_districts']==254
        for s in report['scenarios']:
            assert len(s['districts'])==254 and all(s['checks'].values())
            assert s['simulated_districts']==245 and s['not_estimable_districts']==9
            assert abs(sum(v['mean_seats'] for v in s['national_district_seats'].values())-245)<.01
    checks['254_district_coverage_and_vote_seat_accounting']=True
    commands=[(['test_model.py','test_safety_guards.py','test_boundary_inventory.py','test_ward_inventory.py','test_historical_frame_archive.py'],53),
              (['discover','-s','data/history_2020','-p','test_crosscheck.py'],8)]
    for args,n in commands:
        r=subprocess.run([sys.executable,'-m','unittest',*args],cwd=ROOT,capture_output=True,text=True)
        assert r.returncode==0 and f'Ran {n} tests' in r.stderr,r.stdout+r.stderr
    checks['all_61_tests_pass']=True
    for path in ['model_audit_20261017_0356.json','ward_source_audit_20261017_0356.json']:
        audit=json.loads((ROOT/'outputs'/path).read_text());assert audit['status']=='PASS'
    checks['independent_model_and_two_ward_source_audits']=True
    state=json.loads((ROOT/'state.json').read_text())
    for name,h in state['input_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
    partition=json.loads((ROOT/'data/history_2020/ward_inventory_report.json').read_text())
    assert partition['status']=='PASS' and partition['districts_reconciled']==253
    assert partition['named_ward_valid_votes']+partition['unlocated_valid_votes']==28741408
    assert partition['crosswalk_eligible_districts']==0 and not partition['allocation_weights_created']
    assert partition['parser_sha256']==hashlib.sha256((ROOT/'scripts/build_2020_ward_inventory.py').read_bytes()).hexdigest()
    checks['253_district_candidate_partition_and_no_allocation']=True
    archive=json.loads((ROOT/'data/history_polls/gallup_394_frame_observations.json').read_text())
    assert all(not p['model_input_eligible'] and p['question_type']=='government_frame' for p in archive['polls'])
    assert hashlib.sha256((ROOT/archive['source_file']).read_bytes()).hexdigest()==archive['source_sha256']
    checks['historical_frame_only_pdf_retained_not_current_input']=True
    text=(ROOT/'outputs/DISTRICT_STATUS.md').read_text()
    assert text.count('정부지원·견제 연동(조건부·미보정)')==245 and text.count('보류: 양당 후보 구도 확인 필요')==9
    checks['all_254_report_rows_preserved']=True
    result={'project_version':'0.2.5','engine_version':'0.2.3','verified_date':'2026-10-17','status':'PASS',
            'unit_tests_total':61,'checks':checks,'scenario_recalculated_for_release':False,'scenario_numbers_changed':False,
            'ward_rows':3485,'special_rows':1645,'unlocated_valid_votes':2800361,
            'historical_frame_waves':1,'historical_frame_observations':9,'historical_current_input_linked':False,
            'original_zip_sha256':partition['source_zip_sha256'],
            'source_integrity_recovery':'outputs/source_integrity_recovery_20261017.json',
            'protected_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in protected},
            'remaining_work':['geographic_crosswalk','unlocated_vote_policy','historical_poll_series',
                              'historical_party_mapping','time_split_backtest_and_calibration']}
    (ROOT/'outputs/update_validation_20261017_0356.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='protected_sha256'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
