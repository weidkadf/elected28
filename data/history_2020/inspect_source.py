#!/usr/bin/env python3
"""Inspect, do NOT silently repair or use this source as a model input."""
import csv,collections,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parent
raw=root/'nec_2020_raw.csv'
rows=list(csv.DictReader(raw.open(encoding='cp949')))
bad=[{'csv_line':i+2,**r} for i,r in enumerate(rows) if not r['득표수'].lstrip('-').isdigit()]
meta={
 'status':'QUARANTINED_SOURCE_FORMAT_ERROR',
 'publisher':'중앙선거관리위원회',
 'election_date':'2020-04-15',
 'retrieved_date':'2026-10-16',
 'source_url':'https://www.data.go.kr/data/15025527/fileData.do',
 'history_detail_url':'https://www.data.go.kr/tcs/dss/selectDpkDetailInfo.do?publicDataDetailPk=uddi%3A796a3d01-5143-493e-87a5-a4651d8335b9&publicDataHistSn=10',
 'download_url':'https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003172716&fileDetailSn=1&insertDataPrcus=N',
 'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),
 'raw_bytes':raw.stat().st_size,
 'raw_encoding':'cp949',
 'raw_data_rows':len(rows),
 'district_count':len({(r['시도명'],r['선거구명']) for r in rows}),
 'distinct_candidate_labels':sorted({r['후보자'] for r in rows}),
 'nonnumeric_vote_rows':len(bad),
 'nonnumeric_nonempty_vote_rows':sum(bool(r['득표수']) for r in bad),
 'nonnumeric_examples':bad[:20],
 'license':'공공저작물 출처표시 제1유형',
 'notes':[
 '공식 공개 CSV 자체의 후보자 열이 종로구 후보명으로 고정되어 타지역 후보명은 득표수 열에 문자열로 나타남.',
 '예: 중구성동구갑 후보자=더불어민주당 이낙연, 득표수=더불어민주당 홍익표. 이후 숫자표 또한 고정 종로 후보명에 붙어 있음.',
 '이 원문은 단순 groupby로 집계하면 잘못된 정당/후보 득표가 된다. 검증 전 모델 입력 금지.',
 '복구하려면 지역구마다 삽입된 후보명 헤더를 별도로 해석하고 모든 253개 지역구의 후보명·유효표·당선자를 독립 공식 원본과 대조해야 한다.',
 '대안 공식 XLSX 경로 https://data.nec.go.kr/open-data/file.do?dataId=9 는 접속 타임아웃/502 확인. 해당 사이트 정상시 제21대 XLSX 우선 확보.',
 '2020년 253개 지역구와 2024년 254개 지역구는 이름이 같아도 경계동일성을 가정하지 말 것. 읍면동/투표구 매핑, 경계변경 교차표 필요.',
 '미래통합당 등 2020 정당은 당시 표기로 보존. 이후 계보 연결도 명시적 별도 매핑 필요.',
 '정제 후보별 결과 및 백테스트 성적을 생성하지 않았으며 검증되지 않은 보정값도 저장하지 않음.'
 ]}
(root/'source_quality_report.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:meta[k] for k in ['status','raw_data_rows','district_count','nonnumeric_vote_rows','nonnumeric_nonempty_vote_rows']},ensure_ascii=False,indent=2))
