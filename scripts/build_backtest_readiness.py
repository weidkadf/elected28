#!/usr/bin/env python3
"""As-of historical archive routing only: no fitted backtest or live-model use."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.validate_historical_frames import archive_inventory, parse_day, require, SCOPES

CUTOFFS = ('2024-03-14', '2024-03-15', '2024-03-16', '2024-03-29', '2024-04-09')
BLOCKERS = (
    'historical_baseline_result_availability_not_approved',
    'geographic_crosswalk_not_approved',
    'joint_unlocated_vote_policy_not_approved',
    'original_party_candidate_coalition_mapping_not_approved',
    'cross_election_method_comparability_not_approved',
    'historical_fitting_and_time_split_calibration_not_implemented',
)
FIELDS = ('poll_id', 'scope', 'published_at', 'target_election_date', 'role_profile_id',
          'governing_party', 'main_opposition_party', 'democratic_coordinate_component',
          'source_file', 'source_sha256', 'sample_size', 'weighted_sample_size',
          'suppressed', 'overlap_group')


def split_as_of(inventory, baseline_election, target_election, cutoff):
    """Route validated poll metadata by exact election and conservative cutoff.

    These are archive references, not a feature matrix. Unknown publication time
    excludes the whole publication date. Future/unrelated rows never enter the
    selected manifest or its hash. Source values remain in the validated archive.
    """
    baseline, target, as_of = map(parse_day, (baseline_election, target_election, cutoff))
    require(baseline < as_of < target, 'require baseline election < cutoff < target election')
    require(inventory.get('status') == 'PASS', 'validated archive required')
    require(inventory.get('party_support_used') is False, 'party support forbidden')
    groups = {'baseline_frame_archive': [], 'target_frame_archive': []}
    seen = set()
    for row in inventory['observations']:
        election = row.get('target_election_date')
        if election not in (baseline_election, target_election):
            continue
        published = parse_day(row['published_at'])
        if published >= as_of:
            continue
        require(published < parse_day(election), 'poll published after its target election')
        require(row.get('model_input_eligible') is False, 'archive cannot authorize model input')
        require(row['scope'] in SCOPES, 'unknown scope')
        require(row['poll_id'] not in seen, 'duplicate poll id')
        seen.add(row['poll_id'])
        name = 'baseline_frame_archive' if election == baseline_election else 'target_frame_archive'
        groups[name].append({k: row[k] for k in FIELDS})
    for name, rows in groups.items():
        rows.sort(key=lambda r: r['poll_id'])
        waves = {}
        for row in rows:
            key = (row['source_file'], row['source_sha256'], row['published_at'], row['overlap_group'])
            waves.setdefault(key, []).append(row)
        for rows_in_wave in waves.values():
            require(len(rows_in_wave) == 9 and {r['scope'] for r in rows_in_wave} == SCOPES,
                    'whole national/eight-region wave required')
        groups[name] = {'wave_count': len(waves), 'observation_count': len(rows), 'observations': rows}
    selected = {'baseline_election': baseline_election, 'target_election': target_election,
                'cutoff': cutoff, 'publication_policy': 'published_date_strictly_before_cutoff',
                **groups}
    encoded = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return {**selected, 'selected_manifest_sha256': hashlib.sha256(encoded).hexdigest()}


def readiness_report(root=ROOT):
    root = Path(root)
    paths = list((root / 'data/history_polls').glob('*_frame_observations.json'))
    inventory = archive_inventory(root, paths, '2026-10-18')
    folds = []
    for cutoff in CUTOFFS:
        selected = split_as_of(inventory, '2020-04-15', '2024-04-10', cutoff)
        blockers = list(BLOCKERS)
        if not selected['baseline_frame_archive']['wave_count']:
            blockers.append('no_baseline_frame_wave_available')
        if not selected['target_frame_archive']['wave_count']:
            blockers.append('no_target_frame_wave_available')
        folds.append({'status': 'BLOCKED', 'backtest_executed': False,
                      'selected_archive_manifest': selected, 'blockers': blockers})
    return {'schema_version': 'historical_backtest_readiness_1',
            'status': 'PREPARATION_ONLY', 'generated_date': '2026-10-18',
            'fold_count': len(folds), 'executable_fold_count': 0,
            'backtest_executed': False, 'fitted_coefficients': None, 'performance_metrics': None,
            'party_support_used': False, 'target_election_result_used_as_input': False,
            'current_model_linked': False, 'training_approved': False,
            'national_and_regions_independent': False,
            'method_pooling_approved': False, 'geography_approved': False,
            'folds': folds,
            'limitations': [
                'Only the separately verified historical archive is routed; current polls.json is not imported.',
                'Five cutoffs are a preparation grid, not five independent elections or scored folds.',
                'Available poll references do not establish historical availability of baseline results.',
                'No result labels, candidate vote arrays, model fitting, or accuracy metrics are loaded.',
                'Current 2024-result-based engine must not be used to predict that same election.',
                'To unblock execution implement and review the missing gates; no boolean override is offered.']}


if __name__ == '__main__':
    report = readiness_report()
    (ROOT / 'outputs/backtest_readiness.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('folds', 'limitations')}, ensure_ascii=False))
