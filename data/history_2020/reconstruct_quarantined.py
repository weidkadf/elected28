#!/usr/bin/env python3
"""Reconstruct fixed-slot NEC CSV, retaining quarantine until independent checks.
Never produces or modifies model input files. Python standard library only.
"""
import collections,csv,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RAW=ROOT/'nec_2020_raw.csv'
EXPECTED_SHA='44bdb7be9caf743ea2a897ede8f9ccd4587bed89c5d03fe7b82dff5c1df40f04'

def reconstruct():
    digest=hashlib.sha256(RAW.read_bytes()).hexdigest()
    assert digest==EXPECTED_SHA, 'Source changed: inspect before adapting parser'
    with RAW.open(encoding='cp949',newline='') as f: rows=list(csv.DictReader(f))
    assert len(rows)%15==0
    slot_labels=[r['후보자'] for r in rows[:15]]
    assert slot_labels[:2]==['선거인수','투표수']
    assert slot_labels[-2:]==['무효 투표수','기권자수']
    districts={}; headers=[]; numeric_blocks=0; seen=set(); last_key=None
    for offset in range(0,len(rows),15):
        block=rows[offset:offset+15]; key=(block[0]['시도명'],block[0]['선거구명'])
        assert all((r['시도명'],r['선거구명'])==key for r in block)
        assert all((r['법정읍면동명'],r['투표구명'])==(block[0]['법정읍면동명'],block[0]['투표구명']) for r in block)
        assert [r['후보자'] for r in block]==slot_labels
        values=[r['득표수'] for r in block]
        is_header=any(not v.lstrip('-').isdigit() for v in values)
        new_district=key!=last_key
        if new_district:
            assert key not in seen, 'Noncontiguous district'
            seen.add(key)
            if offset==0:
                assert not is_header
                candidates=slot_labels[2:13]
            else:
                assert is_header, 'Missing district slot header'
                assert values[:2]==['0','0'] and values[-2:]==['0','0']
                candidates=values[2:13]
            nonempty=[c for c in candidates if c]
            assert len(nonempty)==len(set(nonempty))
            assert candidates[:len(nonempty)]==nonempty, 'Nontrailing candidate holes'
            assert all(' ' in c for c in nonempty)
            districts[key]={'labels':candidates,'votes':[0]*11,'electors':0,'ballots':0,'invalid':0,'abstentions':0,'blocks':0,'source_start_line':offset+2}
        d=districts[key]
        if is_header:
            assert new_district and offset>0, 'Unexpected nonnumeric body'
            headers.append({'province':key[0],'district':key[1],'csv_line':offset+2,'candidate_count':sum(bool(c) for c in d['labels'])})
        else:
            n=list(map(int,values))
            assert all(x>=0 for x in n[:14]), 'Negative count except correction abstentions'
            assert sum(n[2:13])+n[13]==n[1], ('Ballot identity failed',offset+2)
            assert n[0]==n[1]+n[14], ('Elector identity failed',offset+2)
            for i,label in enumerate(d['labels']):
                if not label: assert n[i+2]==0, 'Unnamed slot has votes'
                d['votes'][i]+=n[i+2]
            d['electors']+=n[0];d['ballots']+=n[1];d['invalid']+=n[13];d['abstentions']+=n[14];d['blocks']+=1
            numeric_blocks+=1
        last_key=key
    assert len(districts)==253 and len(headers)==252
    out=[]; totals=[]; winners=collections.Counter()
    for (province,district),d in districts.items():
        valid=sum(d['votes']); assert valid+d['invalid']==d['ballots']
        assert d['electors']==d['ballots']+d['abstentions']
        assert valid>0
        maxvote=max(d['votes']);assert d['votes'].count(maxvote)==1
        for i,label in enumerate(d['labels']):
            if not label: continue
            party,candidate=label.rsplit(' ',1)
            winner=d['votes'][i]==maxvote
            if winner: winners[party]+=1
            out.append({'province':province,'district':district,'party_original':party,'candidate':candidate,'votes':d['votes'][i],'valid_votes':valid,'share':d['votes'][i]/valid,'winner_reconstructed':int(winner),'validation_status':'QUARANTINED_PENDING_INDEPENDENT_DISTRICT_CHECK'})
        totals.append({'province':province,'district':district,'electors':d['electors'],'ballots':d['ballots'],'valid':valid,'invalid':d['invalid'],'abstentions':d['abstentions'],'candidate_count':sum(bool(x) for x in d['labels']),'blocks':d['blocks']})
    for name,data in [('reconstructed_candidates_QUARANTINED.csv',out),('reconstructed_district_totals_QUARANTINED.csv',totals)]:
        with (ROOT/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    report={'status':'STRUCTURE_RECOVERED_QUARANTINED_PENDING_INDEPENDENT_CHECK','model_eligible':False,'raw_sha256':digest,'raw_unchanged':True,'raw_rows':len(rows),'block_width':15,'embedded_headers':len(headers),'header_cells_explaining_all_nonnumeric_rows':len(headers)*11,'numeric_blocks_checked':numeric_blocks,'ballot_identities_passed':numeric_blocks,'elector_identities_passed':numeric_blocks,'unnamed_slot_nonzero_count':0,'districts':len(districts),'reconstructed_candidate_labels':len(out),'reconstructed_winners':dict(winners),'national_totals':{k:sum(d[k] for d in totals) for k in ['electors','ballots','valid','invalid','abstentions']},'independent_check_status':'NOT_COMPLETED_FOR_253_DISTRICTS','notes':['모든 후보명을 종로구 이름으로 고정한 원문의 후보자 필드는 열 슬롯 식별자일 뿐이다.','종로 이후 252개 지역구의 첫 15행은 후보명을 담은 삽입 헤더이다. 11칸 중 실제 후보 외 빈칸은 다음 모든 수치 블록에서 0임을 검증했다.','헤더의 읍면동 이름은 직전 행의 잘못 투입·구분된 투표지 값이 남아 있으므로 숫자 투표행과 혼동하지 않는다.','모든 수치블록 내부 산술일치는 독립 원본 대조를 대체하지 않는다. 당선자 이름·정당·유효표·후보득표 253지역구 독립 검증 전 학습·백테스트 투입 금지.','2020↔2024 지역구 경계동일성 미검증. 이 파일은 2020 원래 경계만 나타낸다.']}
    (ROOT/'reconstruction_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': reconstruct()
