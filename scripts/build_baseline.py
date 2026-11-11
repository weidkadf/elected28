#!/usr/bin/env python3
"""Fetch and aggregate official NEC 2024 constituency returns. Stdlib only."""
import argparse, collections, csv, datetime, hashlib, io, json, re, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
SOURCE='https://www.data.go.kr/data/15025527/fileData.do'
DOWNLOAD='https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003172714&fileDetailSn=1&insertDataPrcus=N'
NON_CANDIDATES={'선거인수','투표수','무효 투표수','기권자수'}
EXPECTED_REGIONS={'서울특별시':48,'부산광역시':18,'대구광역시':12,'인천광역시':14,'광주광역시':8,'대전광역시':7,'울산광역시':6,'세종특별자치시':2,'경기도':60,'강원특별자치도':8,'충청북도':8,'충청남도':11,'전북특별자치도':10,'전라남도':10,'경상북도':13,'경상남도':16,'제주특별자치도':3}
REGION_CODES={'서울특별시':'11','부산광역시':'26','대구광역시':'27','인천광역시':'28','광주광역시':'29','대전광역시':'30','울산광역시':'31','세종특별자치시':'36','경기도':'41','강원특별자치도':'51','충청북도':'43','충청남도':'44','전북특별자치도':'52','전라남도':'46','경상북도':'47','경상남도':'48','제주특별자치도':'50'}
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');args=parser.parse_args()
 raw=DATA/'raw'/'nec_2024.csv';raw.parent.mkdir(parents=True,exist_ok=True)
 if args.download or not raw.exists():
  raw.write_bytes(urllib.request.urlopen(DOWNLOAD,timeout=60).read())
 payload=raw.read_bytes();rows=list(csv.DictReader(io.StringIO(payload.decode('cp949'))))
 votes=collections.Counter(); totals=collections.defaultdict(collections.Counter);candidate_names={}
 for row in rows:
  reg,dist=row['시도명'],row['선거구명']; label=row['후보자']; val=int(row['득표수'])
  if label in NON_CANDIDATES:totals[(reg,dist)][label]+=val;continue
  assert val>=0,(row,'negative candidate vote')
  party,candidate=label.split(' ',1)
  votes[(reg,dist,party,candidate)]+=val
 bydistrict=collections.defaultdict(list)
 for (reg,dist,party,candidate),v in votes.items():bydistrict[(reg,dist)].append((party,candidate,v))
 region_counts=dict(collections.Counter(reg for reg,dist in bydistrict))
 assert region_counts==EXPECTED_REGIONS,(region_counts,EXPECTED_REGIONS)
 assert len(bydistrict)==254
 out=[]; districts=[];wins=collections.Counter();partytotals=collections.Counter()
 for reg,dist in sorted(bydistrict,key=lambda k:(REGION_CODES[k[0]],k[1])):
  candidates=sorted(bydistrict[(reg,dist)],key=lambda c:(-c[2],c[0],c[1]));valid=sum(c[2] for c in candidates)
  assert valid==totals[(reg,dist)]['투표수']-totals[(reg,dist)]['무효 투표수'],(reg,dist,'valid reconciliation')
  # Project-local stable identifier; deliberately NOT a purported official NEC code.
  did=f'2024-{REGION_CODES[reg]}-{dist}'
  win=candidates[0];wins[win[0]]+=1
  for rank,(party,candidate,v) in enumerate(candidates,1):
   partytotals[party]+=v
   out.append({'district_id':did,'region':reg,'district_name':dist,'party':party,'candidate':candidate,'votes':v,'valid_votes':valid,'source_url':SOURCE,'election_date':'2024-04-10','vote_share':v/valid,'rank':rank,'elected':rank==1})
  districts.append({'district_id':did,'region':reg,'district_name':dist,'valid_votes':valid,'winner_party':win[0],'winner_candidate':win[1],'winner_share':win[2]/valid,'runner_up_party':candidates[1][0],'runner_up_candidate':candidates[1][1],'runner_up_share':candidates[1][2]/valid,'margin_pp':(win[2]-candidates[1][2])/valid*100,'candidate_count':len(candidates),'election_date':'2024-04-10','source_url':SOURCE})
 assert dict(wins)=={'더불어민주당':161,'국민의힘':90,'진보당':1,'새로운미래':1,'개혁신당':1},wins
 assert sum(partytotals.values())==29234129,partytotals
 for name,records in [('baseline_2024.csv',out),('districts_2024.csv',districts)]:
  with (DATA/name).open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=records[0].keys());w.writeheader();w.writerows(records)
 metadata={'dataset':'제22대 국회의원선거 지역구 개표결과','publisher':'중앙선거관리위원회','source_url':SOURCE,'download_url':DOWNLOAD,'source_date':'2024-04-10','retrieved_date':'2026-10-16','raw_encoding':'cp949','raw_sha256':hashlib.sha256(payload).hexdigest(),'raw_bytes':len(payload),'raw_rows':len(rows),'district_count':len(districts),'candidate_count':len(out),'valid_vote_total':sum(partytotals.values()),'winner_counts':dict(wins),'region_counts':region_counts,'party_vote_totals':dict(partytotals),'license':'공공저작물 출처표시 제1유형','missing_fields':[],'checks':{'all_254_constituencies':True,'all_17_region_counts':True,'candidate_votes_nonnegative':True,'every_district_valid_equals_cast_minus_invalid':True,'winner_totals_match_161_90_1_1_1':True,'national_valid_total_matches_29234129':True},'notes':['선거구·후보별 투표구 득표수 합산. 원문에는 선거구 합계 행이 없어 중복 집계하지 않음.','원문 후보자 열은 정당명과 이름으로 분리. 통계행 선거인수/투표수/무효 투표수/기권자수 제외.','일부 원문 기권자수 행 음수 248건은 후보 득표가 아니므로 득표에 포함하지 않음.','district_id는 프로젝트 내부 안정식별자이며 선관위 공식 선거구코드가 아님.','후보별 CSV의 valid_votes는 해당 지역구 유효투표 총수의 반복값이며 후보별 합산 금지.','2024 선거 당시의 정당·후보·경계를 보존함. 이후 당적 변경·재보궐·2028 획정은 반영하지 않음.','사퇴·등록무효 후보가 최종 개표 원문에 없다면 이 자료에도 없으며 전체 등록후보 명부와 다를 수 있음.']}
 (DATA/'baseline_2024_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:metadata[k] for k in ['district_count','candidate_count','valid_vote_total','winner_counts','checks']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
