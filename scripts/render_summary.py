#!/usr/bin/env python3
"""Render auditable district coverage; explicitly distinguish scenarios from forecasts."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    with (ROOT / 'data/districts_2024.csv').open(encoding='utf-8-sig') as f:
        districts = list(csv.DictReader(f))
    polls = json.loads((ROOT / 'data/polls.json').read_text())
    report_path = ROOT / 'outputs/model_report.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    state = json.loads((ROOT / 'state.json').read_text())
    history_path = ROOT / 'outputs/historical_frame_inventory.json'
    history = json.loads(history_path.read_text()) if history_path.exists() else {}
    diagnostic_path = ROOT / 'outputs/optional_remainder_diagnostic_253.json'
    diagnostic = json.loads(diagnostic_path.read_text()) if diagnostic_path.exists() else {}
    boundary_path = ROOT / 'data/boundary_research/boundary_review_254.json'
    boundaries = {d['district_id']:d for d in json.loads(boundary_path.read_text())} if boundary_path.exists() else {}
    boundary_labels = {'same_name_same_statutory_text_geometry_unverified':'문구 동일·지리 미검증',
                       'same_name_statutory_text_diff_review_required':'동일명칭·문구 차이',
                       'no_same_name_predecessor_review_required':'동일명칭 전신 없음'}
    scenarios = report.get('scenarios', [])
    lines = ['# 23대 총선 모델 — 전국 지역구 현황', '',
             f"자료 기준일: {polls['as_of']} · 기준 선거구: 2024년 254개 · 프로젝트: {state['version']} · 엔진: {report.get('schema_version','확인 대기')}", '',
             '**현재 단계: 공식 기초자료 검증 및 미보정 시나리오 엔진. 검증된 2028년 당선확률은 아직 산출하지 않습니다.**', '',
             '주입력은 정부지원·견제 여론입니다. 정당 지지도는 계산에서 완전히 제외했습니다. 2024년과 현재의 여야 지위 전환을 반영하며, 아래 2024 결과는 사실이고 시나리오는 명시한 가정 아래의 실험입니다.', '',
             '2026-11-03 개발 갱신: 2020년 하위 투표행을 유형별로 분리 검증했습니다. 관내사전투표 8,925,666표는 투표소 소재 동의 거주자 표로 간주하지 않습니다. 지리 변환·백테스트는 미완료이며 현재 시나리오는 변경하지 않았습니다. 저장소는 Google Drive입니다.', '', '## 입력 확보', '', '| 조사 | 문항 | 지역 | 표본 | 검증 |', '|---|---|---|---:|---|']
    for p in polls['polls']:
        if p.get('question_type') != 'government_frame':
            continue
        lines.append(f"| {p['poll_id']} | {p['question_type']} | {p['scope']} | {p.get('sample_size','')} | {p.get('verification_status','')} |")
    lines += ['', '## 기준 선거구 전체', '',
              '득표차는 2024년 1위와 2위의 유효득표율 차이입니다. 과거 당선인의 이름은 2028년 후보 확정을 뜻하지 않습니다. 현재 예측 상태는 후보·획정·검증 정보가 부족하여 미보정입니다.', '',
              '마지막 열은 2020→2024 법정 구역문구 비교이며, 23대 획정 확정이나 지리 경계 동일성 판정이 아닙니다. 문구가 같은 지역도 행정구역 변동 검증이 필요합니다.', '',
              '| 지역 | 선거구 | 2024 당선 정당 | 2024 당선인 | 1·2위 차이(%p) | 2028 상태 | 2020→2024 구역문구 |',
              '|---|---|---|---|---:|---|---|']
    statuses = {d['district_id']: d for d in (scenarios[0]['districts'] if scenarios else [])}
    for d in districts:
        result = statuses.get(d['district_id'], {})
        label = '정부지원·견제 연동(조건부·미보정)' if result.get('status') == 'experimental_conditional_frame_scenario' else '보류: 양당 후보 구도 확인 필요' if result.get('status') == 'not_estimable' else '모형 입력 확인 대기'
        boundary_label = boundary_labels.get(boundaries.get(d['district_id'],{}).get('review_status'), '검토 대기')
        lines.append(f"| {d['region']} | {d['district_name']} | {d['winner_party']} | {d['winner_candidate']} | {float(d['margin_pp']):.2f} | {label} | {boundary_label} |")
    if scenarios:
        lines += ['', '## 여건 변화 민감도 실험', '',
                  '**아래는 검증 전 조건부 시나리오입니다.** 2024년 실제 득표에 여야 지위를 맞춘 정부지원·견제 변화량을 연동했습니다. 정당 지지도는 사용하지 않습니다. 제3후보 표·후보 구도·경계는 조건부 고정이며, 양당 후보가 함께 없던 지역은 보류합니다. 시뮬레이션 빈도는 검증된 당선확률이 아닙니다.', '',
                  '| 시나리오 | 민주당 평균 지역구 | 국민의힘 평균 지역구 | 기타 평균 지역구 | 계산 지역구 | 보류 지역구 |', '|---|---:|---:|---:|---:|---:|']
        for s in scenarios:
            n = s.get('national_district_seats', {})
            alpha = s['assumptions']['transfer_coefficient']
            label = {0:'무연동 대조 (α=0)', 0.5:'절반 연동 가정 (α=0.5)', 1:'완전 연동 스트레스 실험 (α=1)'}.get(alpha, f'α={alpha}')
            other = sum(v['mean_seats'] for k,v in n.items() if k not in ['더불어민주당','국민의힘'])
            lines.append(f"| {label} | {round(n.get('더불어민주당',{}).get('mean_seats',0))} | {round(n.get('국민의힘',{}).get('mean_seats',0))} | {round(other)} | {s.get('simulated_districts','')} | {s.get('not_estimable_districts','')} |")
        lines += ['', '어떤 계수도 가장 유력한 예측으로 선정하지 않았습니다. α=1은 강한 연동을 가정한 스트레스 실험입니다. α=0도 가정한 오차를 포함하므로 2024년 확정 의석과 다릅니다. 표시한 평균 의석은 정수로 반올림했습니다. 보류 지역구는 위 당별 의석 수에 포함되지 않습니다. 전국 254석 확정 예측처럼 해석하지 마세요. 각 지역구의 시나리오별 득표 구간 및 모의 승리 빈도는 `outputs/model_report.json`에 있습니다. 이 구간은 임의로 둔 오차 규모에 조건부인 시나리오 구간이며 통계적 신뢰구간이 아닙니다.']
    lines += ['', '## 이번 검증 갱신', '',
              f"프로젝트{state['version']}: 과거 정부지원·견제 원문 {history.get('wave_count',0)}시점·{history.get('observation_count',0)}개 전국/권역 관측은 현행 모델과 분리 보관합니다. 같은 조사 전국/권역은 독립 표본이 아니며, 발표시각 미확인 자료는 역사 컷오프 당일을 제외합니다. 총{state.get('unit_test_count',79)}개 회귀검사 대상으로 정당지지도 변경·삭제 불변성과 원문 무결성을 점검합니다. 현행 입력/엔진0.2.3·기존 시나리오 수치는 보존하고 재산출하지 않습니다. 최종 검증: {state['latest_validation']}.",
              '', '역사 아카이브는2020년 민주당 여당/미래통합당 야당의 정부지원 방향과2024년 국민의힘 여당/민주당 야당의 정부견제 방향을 별도 검토 프로필로 확인합니다. RDD/가상번호 방식 차이도 보존하며 원정당 자동 치환·자동 혼합·학습 승인은 하지 않습니다. 578호·579호·580호 주간의 역사 보관은 현행580호 기준값 교체가 아닙니다. 월간 통합은 추가 가중하지 않습니다.579호는03/22 당일 제외·03/23부터,580호는03/29 당일 제외·03/30부터 자료 목록에 포함합니다.',
              '', '과거 백테스트 준비 목록(outputs/backtest_readiness.json)은2024년 다섯 기준일에서 정부지원·견제 자료를 선거별로 구분합니다. 공개일 당일/미래 자료는 제외하며, 지리·기준선 공개근거·후보연합·방법비교·학습하니스 미완료로 모두BLOCKED입니다. 실제 백테스트나 보정 완료를 뜻하지 않습니다.',
              '', '## 별도항목 부분식별 수학 도구 — 지리 변환 아님', '',
              f"원2020구역 {diagnostic.get('diagnostic_district_count',0)}곳에서 전체 동소계 L에 원후보별 별도항목 x∈[0,U]를 일부 포함/제외하는 인위적 민감도를 진단했습니다. 제3후보·무소속을 유지하고 후보별 득표율 주변 상·하한을 계산합니다. 엄격1위 견고{diagnostic.get('lead_status_counts',{}).get('strict_leader_robust_to_optional_remainder',0)}곳·미인증{diagnostic.get('lead_status_counts',{}).get('no_strict_leader_certified_under_box',0)}곳은 이 진단의 결과이며 실제2020 당선자의 불확실성이나2024/2028 의석 예측이 아닙니다. 2020 전체 확정결과는 x=U에서 복원됩니다. 후보별 극값도 동시에 달성되는 하나의 득표구성이 아닙니다. 결과: outputs/optional_remainder_diagnostic_253.json.",
              '', '이동 동·새 구역으로 별도표2,800,361표를 귀속할 지리 근거와 여러 수신구역의 공동 보존 제약은 여전히 미확인입니다. 지리승인0·학습승인false·현행연동false를 유지하며, 이 도구를 득표 변환표·확률구간·국가 의석범위로 쓰지 않습니다.',
              '', '## 다중 수신구역 공동보존 검사 — 합성 예제만', '',
              '원지역구·원정당·원후보별 동소계와 별도표가 각각 수신구역 합계와 일치하는지 검사하는 도구를 추가했습니다. 같은 표의 중복 배분이나 서로 다른 출발지의 과다·과소 배분 상쇄를 거부합니다. 합성 예제의 산술 검사일 뿐 실제 지리 대응·배분표·가중치·당선확률을 생성하지 않습니다. 지리 승인0·실제 백테스트0·현행 시나리오 불변입니다. 결과: outputs/joint_vote_conservation_synthetic.json.',
              '', '## 다음 단계', '',
              '21대 자료와 선거구 변환, 시점별 조사 아카이브, 과거선거 백테스트, 지역구별 후보 조사, 2026 재보선·당적 변동을 순차 반영합니다. 자세한 잔여 작업은 `BACKLOG.md`, 갱신 규칙은 `UPDATE_PROTOCOL.md`를 참고하세요.', '',
              '원출처: 중앙선거관리위원회 공공데이터 https://www.data.go.kr/data/15025527/fileData.do',
              '조사 원문 URL과 접근·검증 상태: `data/polls.json`, `poll_sources.md`.', '']
    (ROOT / 'outputs').mkdir(exist_ok=True)
    (ROOT / 'outputs/DISTRICT_STATUS.md').write_text('\n'.join(lines), encoding='utf-8')

if __name__ == '__main__':
    main()
