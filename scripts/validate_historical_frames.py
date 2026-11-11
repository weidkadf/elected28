#!/usr/bin/env python3
"""Validate a frame-only historical archive; never feed or fit the live engine.

An inventory is NOT training approval. Date-only cutoffs conservatively exclude
the publication day because an unknown release time cannot establish availability.
"""
import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPES = {'national', '서울', '인천/경기', '강원', '대전/세종/충청',
          '광주/전라', '대구/경북', '부산/울산/경남', '제주'}
OPTIONS = ['현 정부를 지원하기 위해 여당 후보가 많이 당선돼야 한다',
           '현 정부를 견제하기 위해 야당 후보가 많이 당선돼야 한다']
SHARES = {'정부지원', '정부견제', '모름/응답거절'}
# Explicit original identities and methods; NOT successor maps or pooling approval.
# The 2024 two-option profile starts at the newly checked 578 wave, not at the
# earlier three-option January/February/March surveys shown on its trend graph.
REVIEWED_PROFILES = {'2020-04-15': {
                  'profile_id': 'gallup_2020_rdd_support_dem',
                  'target_election_date': '2020-04-15',
                  'fieldwork_start_min': '2020-03-01',
                  'fieldwork_end_max': '2020-04-14',
                  'governing_party': '더불어민주당',
                  'main_opposition_party': '미래통합당',
                  'democratic_coordinate_component': '정부지원',
                  'population': '전국 만 18세 이상',
                  'sampling': '휴대전화 RDD 무작위 추출, 집전화 RDD 15% 포함',
                  'mode': '전화조사원 인터뷰'},
    '2024-04-10': {'profile_id': 'gallup_2024_virtual_mobile_check_dem',
                  'target_election_date': '2024-04-10',
                  'fieldwork_start_min': '2024-03-12',
                  'fieldwork_end_max': '2024-03-31',
                  'governing_party': '국민의힘',
                  'main_opposition_party': '더불어민주당',
                  'democratic_coordinate_component': '정부견제',
                  'population': '전국 만 18세 이상 유권자',
                  'sampling': '이동통신 3사 제공 무선전화 가상번호 무작위 추출',
                  'mode': '전화조사원 인터뷰(CATI)'}}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse_day(value):
    require(isinstance(value, str), 'date must be an ISO date string')
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, 'date must use YYYY-MM-DD')
    return parsed


def positive_integer(value):
    return type(value) is int and value > 0


def archive_inventory(root, paths, as_of):
    """Return candidate coverage only; exclude non-frame records before parsing."""
    root = Path(root).resolve()
    cutoff = parse_day(as_of)
    rows, waves, seen_ids, seen_observations = [], {}, set(), set()
    paths = sorted(map(Path, paths))
    require(paths, 'no archive files found')
    for path in paths:
        doc = json.loads(path.read_text())
        require(doc.get('party_support_included') is False, 'archive must be frame-only')
        selected = [p for p in doc['polls'] if p.get('question_type') == 'government_frame']
        require(selected, 'archive has no frame observations')
        source = (root / doc['source_file']).resolve()
        require(source.is_relative_to(root), 'source escapes project directory')
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        require(raw.startswith(b'%PDF-') and digest == doc['source_sha256'], 'source PDF integrity failed')
        source_rel = source.relative_to(root).as_posix()
        for p in selected:
            require(p.get('model_input_eligible') is False and p.get('party_support_used') is False
                    and p.get('direct_vote_mapping_allowed') is False, 'archive eligibility violation')
            require(p.get('opposition_judgment_directly_measured') is False,
                    'government support is not a direct opposition-judgment item')
            require(p.get('answer_options_exact') == OPTIONS, 'unreviewed question wording')
            require(p.get('series_id') == 'gallup_daily_election_expectation', 'unreviewed series')
            require(p.get('source_file') == source_rel and p.get('pdf_sha256') == digest
                    and p.get('pdf_bytes') == len(raw), 'record/source mismatch')
            require(str(p.get('source_url', '')).startswith('https://www.gallup.co.kr/'), 'primary source required')
            require(p.get('pollster') == '한국갤럽', 'unreviewed pollster')
            require(p.get('publication_timezone') == 'Asia/Seoul' and p.get('publication_time') is None,
                    'only reviewed date-only publication evidence is supported')
            require(bool(p.get('publication_date_evidence')), 'publication evidence missing')
            start, end, published, target = [parse_day(p[k]) for k in
                ('fieldwork_start', 'fieldwork_end', 'published_at', 'target_election_date')]
            require(start <= end <= published < target, 'fieldwork/publication/target chronology failed')
            profile = REVIEWED_PROFILES.get(p['target_election_date'])
            require(profile is not None, 'target election profile not reviewed')
            require(parse_day(profile['fieldwork_start_min']) <= start <= end <=
                    parse_day(profile['fieldwork_end_max']), 'role window not reviewed')
            for k in ('target_election_date', 'governing_party', 'main_opposition_party',
                      'democratic_coordinate_component'):
                require(p.get(k) == profile[k], 'original role identity not reviewed: ' + k)
            for k in ('population', 'sampling', 'mode'):
                require(p.get(k) == profile[k], 'method profile not reviewed: ' + k)
            scope = p.get('scope')
            require(scope in SCOPES, 'unknown scope')
            require(positive_integer(p.get('sample_size')) and positive_integer(p.get('weighted_sample_size')),
                    'sample and weighted sample must be separate positive integers')
            require(type(p.get('suppressed')) is bool, 'suppression flag required')
            shares = p.get('shares')
            if p['suppressed']:
                require(scope != 'national' and shares == {}, 'suppressed values must remain missing')
            else:
                require(isinstance(shares, dict) and set(shares) == SHARES, 'three frame shares required')
                require(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
                            for v in shares.values()), 'invalid frame share')
                require(abs(sum(shares.values()) - 1) <= .015000001, 'shares exceed rounding tolerance')
            for k in ('population', 'sampling', 'mode', 'pollster', 'overlap_group'):
                require(isinstance(p.get(k), str) and bool(p[k].strip()), 'method metadata missing: ' + k)
            poll_id = p.get('poll_id')
            require(isinstance(poll_id, str) and poll_id and poll_id not in seen_ids, 'duplicate or empty poll id')
            seen_ids.add(poll_id)
            wave = (p['series_id'], p['fieldwork_start'], p['fieldwork_end'], p['published_at'])
            key = (*wave, scope)
            require(key not in seen_observations, 'duplicate wave/scope observation')
            seen_observations.add(key)
            waves.setdefault(wave, []).append(p)
            rows.append({'poll_id': poll_id, 'scope': scope, 'published_at': p['published_at'],
                         'role_profile_id': profile['profile_id'],
                         'target_election_date': p['target_election_date'],
                         'governing_party': p['governing_party'],
                         'main_opposition_party': p['main_opposition_party'],
                         'democratic_coordinate_component': p['democratic_coordinate_component'],
                         'source_file': source_rel, 'source_sha256': digest,
                         'available_at_cutoff': published < cutoff,
                         'cutoff_exclusion_reason': None if published < cutoff else
                             ('unknown_release_time_on_cutoff_day' if published == cutoff else 'published_after_cutoff'),
                         'suppressed': p['suppressed'], 'sample_size': p['sample_size'],
                         'weighted_sample_size': p['weighted_sample_size'],
                         'overlap_group': p['overlap_group'], 'model_input_eligible': False})
    wave_rows = []
    for key, polls in sorted(waves.items()):
        require({p['scope'] for p in polls} == SCOPES and len(polls) == 9, 'incomplete national/eight-region wave')
        national = next(p for p in polls if p['scope'] == 'national')
        regional = [p for p in polls if p['scope'] != 'national']
        require(sum(p['sample_size'] for p in regional) == national['sample_size'], 'regional raw sample mismatch')
        # Rounded weighted counts may differ by up to one count per regional cell.
        require(abs(sum(p['weighted_sample_size'] for p in regional) - national['weighted_sample_size']) <= 8,
                'regional weighted sample mismatch beyond rounding tolerance')
        for k in ('source_file', 'pdf_sha256', 'overlap_group', 'sampling', 'mode', 'population', 'pollster',
                  'governing_party', 'main_opposition_party', 'answer_options_exact',
                  'target_election_date', 'democratic_coordinate_component'):
            require(all(p[k] == national[k] for p in polls), 'inconsistent within-wave metadata: ' + k)
        wave_rows.append({'series_id': key[0], 'fieldwork_start': key[1], 'fieldwork_end': key[2],
                          'published_at': key[3], 'national_sample_size': national['sample_size'],
                          'role_profile_id': REVIEWED_PROFILES[national['target_election_date']]['profile_id'],
                          'target_election_date': national['target_election_date'],
                          'governing_party': national['governing_party'],
                          'main_opposition_party': national['main_opposition_party'],
                          'democratic_coordinate_component': national['democratic_coordinate_component'],
                          'sampling': national['sampling'], 'mode': national['mode'],
                          'population': national['population'],
                          'answer_options_exact': national['answer_options_exact'],
                          'national_weighted_sample_size': national['weighted_sample_size'],
                          'suppressed_regions': [p['scope'] for p in regional if p['suppressed']],
                          'method_comparability_approved': False})
    return {'schema_version': 'historical_archive_inventory_1', 'status': 'PASS', 'as_of': as_of,
            'wave_count': len(waves), 'observation_count': len(rows),
            'available_observations': sum(r['available_at_cutoff'] for r in rows),
            'publication_policy': 'strictly_before_cutoff_date_unknown_release_time_excludes_same_day',
            'party_support_used': False, 'training_approved': False, 'current_model_linked': False,
            'geography_approved': False, 'party_successor_mapping_created': False,
            'national_and_regions_independent': False, 'wave_pooling_or_weights_created': False,
            'cross_election_pooling_approved': False,
            'target_election_coverage': [
                {'target_election_date': target,
                 'wave_count': sum(w['target_election_date'] == target for w in wave_rows),
                 'observation_count': sum(r['target_election_date'] == target for r in rows),
                 'available_observations': sum(r['target_election_date'] == target and
                                               r['available_at_cutoff'] for r in rows)}
                for target in sorted({r['target_election_date'] for r in rows})],
            'remaining_gates': ['geographic_crosswalk', 'unlocated_vote_policy', 'historical_party_candidate_mapping',
                                'method_comparability', 'historical_baseline_availability', 'time_split_calibration'],
            'waves': wave_rows, 'observations': sorted(rows, key=lambda r: r['poll_id'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--output', default='outputs/historical_frame_inventory.json')
    args = parser.parse_args()
    report = archive_inventory(ROOT, (ROOT / 'data/history_polls').glob('*_frame_observations.json'), args.as_of)
    (ROOT / args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('waves', 'observations')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
