#!/usr/bin/env python3
"""Exact box-constraint vote-share envelopes; no allocation or prediction.

For candidate c: v_c=L_c+x_c, with 0<=x_c<=U_c. L is a fixed subtotal,
U an original-candidate-specific remainder. Marginal extrema are not jointly
attainable vote vectors. This excludes extra geographic constraints and must
not be called a geographic crosswalk. The actual original 2020 result uses x=U.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def count(value):
    require(type(value) is int and value >= 0, 'vote counts must be nonnegative integers, not booleans')
    return value


def candidate_envelope(partition):
    require(isinstance(partition, list) and partition, 'candidate partition is empty')
    observed, seen = [], set()
    for row in partition:
        key = (row.get('party_original'), row.get('candidate'))
        require(all(isinstance(x, str) and x.strip() for x in key), 'original candidate identity missing')
        require(key not in seen, 'duplicate original candidate identity')
        seen.add(key)
        lower, remainder = count(row['named_ward']), count(row['unlocated'])
        require(count(row['total']) == lower + remainder, 'candidate partition does not reconcile')
        observed.append((key, lower, remainder))
    observed.sort()
    total_l = sum(v[1] for v in observed)
    total_u = sum(v[2] for v in observed)
    require(total_l > 0, 'positive fixed subtotal required; empty-target geometry is unsupported')
    output = []
    for key, fixed, uncertain in observed:
        lower = Fraction(fixed, total_l + total_u - uncertain)
        upper = Fraction(fixed + uncertain, total_l + uncertain)
        others = [r for r in observed if r[0] != key]
        # No tie-break assumption: distinguish possible co-lead from strict lead.
        possible_colead = not others or fixed + uncertain >= max(r[1] for r in others)
        possible_strict = not others or fixed + uncertain > max(r[1] for r in others)
        guaranteed_strict = not others or fixed > max(r[1] + r[2] for r in others)
        share_full = Fraction(fixed + uncertain, total_l + total_u)
        require(lower <= share_full <= upper, 'full original result outside envelope')
        output.append({'party_original': key[0], 'candidate': key[1],
                       'fixed_named_ward_votes': fixed, 'candidate_remainder_cap': uncertain,
                       'full_original_votes': fixed + uncertain,
                       'full_original_vote_share': float(share_full),
                       'share_lower': float(lower), 'share_upper': float(upper),
                       'share_lower_exact': [lower.numerator, lower.denominator],
                       'share_upper_exact': [upper.numerator, upper.denominator],
                       'possible_coleader_under_box': possible_colead,
                       'possible_strict_leader_under_box': possible_strict,
                       'guaranteed_strict_leader_under_box': guaranteed_strict})
    return {'fixed_valid_votes': total_l, 'remainder_cap_valid_votes': total_u,
            'full_original_valid_votes': total_l + total_u,
            'joint_extrema_or_probability': False,
            'candidate_envelopes': output}


def build_report(readiness):
    require(isinstance(readiness, list) and len(readiness) == 253, 'all 253 original districts required')
    districts, seen, national_l, national_u = [], set(), 0, 0
    for district in sorted(readiness, key=lambda d: (d['province'], d['district'])):
        key = (district['province'], district['district'])
        require(key not in seen, 'duplicate original district')
        seen.add(key)
        require(district['crosswalk_eligible'] is False, 'input geometry approval is not supported')
        envelope = candidate_envelope(district['candidate_partition'])
        require(envelope['fixed_valid_votes'] == count(district['named_ward_valid_votes'])
                and envelope['remainder_cap_valid_votes'] == count(district['unlocated_valid_votes'])
                and envelope['full_original_valid_votes'] == count(district['valid_votes']), 'district partition mismatch')
        candidate_rows = envelope['candidate_envelopes']
        guaranteed = [c for c in candidate_rows if c['guaranteed_strict_leader_under_box']]
        require(len(guaranteed) <= 1, 'multiple guaranteed strict leaders')
        national_l += envelope['fixed_valid_votes']
        national_u += envelope['remainder_cap_valid_votes']
        districts.append({'province': key[0], 'district_2020': key[1],
                          'status': 'original_ward_plus_optional_remainder_sensitivity_only',
                          'geographic_crosswalk_eligible': False, 'target_district_2024': None,
                          'historical_full_result_is_known': True,
                          'box_lead_status': 'strict_leader_robust_to_optional_remainder' if guaranteed else
                                             'no_strict_leader_certified_under_box',
                          **envelope})
    require(national_l == 25941047 and national_u == 2800361, 'national historical partition mismatch')
    return {'schema_version': 'optional_remainder_box_diagnostic_1', 'status': 'PASS',
            'method': 'exact_marginal_share_envelopes_over_candidate_specific_box',
            'purpose': '原2020 동소계에 별도항목을 일부 포함/제외할 때의 단위선택 민감도 진단; 2024 경계 변환 아님',
            'diagnostic_district_count': 253, 'fixed_valid_votes': national_l,
            'remainder_cap_valid_votes': national_u, 'full_original_valid_votes': national_l + national_u,
            'lead_status_counts': dict(Counter(d['box_lead_status'] for d in districts)),
            'party_support_used': False, 'allocation_weights_created': False,
            'unknown_geography_solved': False, 'geographic_crosswalk_eligible_districts': 0,
            'training_approved': False, 'current_model_linked': False,
            'confidence_intervals_or_win_probabilities': False,
            'joint_geographic_allocation_or_national_seat_bounds': False,
            'limitations': [
                '원지역구 전체2020결과는 이미 확정되며 x=U를 반드시 모두 포함한다.',
                '여기서 x∈[0,U]는 별도항목 포함/제외의 인위적 민감도이며 실제2020결과의 불확실성이 아니다.',
                '후보별 상자 제약 외 지리·관할·투표구·정수분할 제약을 승인하지 않는다.',
                '상한/하한은 서로 다른 극점이며 한 득표벡터처럼 합산하거나 의석확률로 변환하지 않는다.',
                '이동한 동 또는2024/2028지역구에 원지역구 U를 붙일 지리적 근거는 아직 없다.',
                '무소속은 후보별 정체성을 보존하며 제3후보 포함 분모를 사용한다.'
            ], 'districts': districts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='outputs/optional_remainder_diagnostic_253.json')
    args = parser.parse_args()
    path = ROOT / 'data/history_2020/ward_readiness_253.json'
    report = build_report(json.loads(path.read_text()))
    report['source_readiness_file'] = path.relative_to(ROOT).as_posix()
    report['source_readiness_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    report['code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (ROOT / args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('districts', 'limitations')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
