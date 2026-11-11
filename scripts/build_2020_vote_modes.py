#!/usr/bin/env python3
"""Read-only voting-mode bookkeeping; station labels are not residence evidence."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_2020_ward_inventory import all_rows, signed_count, DIRECTORY
from crosscheck_official_tables import ZIP_SHA, METRICS, read_table, display_name, column_number

SPECIAL = {'거소·선상투표', '관외사전투표', '국외부재자투표',
           '국외부재자투표(공관)', '잘못 투입·구분된 투표지'}
JOINT = '둔촌제2동제3투·둔촌제1동투'

def classify(label):
    if label == '관내사전투표':
        return 'internal_advance'
    if label == JOINT:
        return 'joint_station_label'
    if re.fullmatch(r'\S+(?:투|투표소)', label):
        return 'ordinary_station_label'
    raise ValueError('Unknown child label: ' + label)

def parse_rows(rows, columns):
    parents, children, special = [], [], []
    seen_rows, parent_names, special_names = set(), set(), set()
    parent = None
    def finish():
        if parent is None:
            return
        subset = [x for x in children if x['parent_row'] == parent['row']]
        if sum(x['mode'] == 'internal_advance' for x in subset) != 1:
            raise ValueError('Exactly one internal advance row required')
        for field in ('votes', 'metrics'):
            for key, value in parent[field].items():
                if sum(x[field][key] for x in subset) != value:
                    raise ValueError('Parent child mismatch')
    for rownum, cells in rows:
        if rownum in seen_rows:
            raise ValueError('Duplicate row number')
        seen_rows.add(rownum)
        if rownum <= 7:
            continue
        a, b = cells.get('A', '').strip(), cells.get('B', '').strip()
        if not a and not b:
            if any(str(v).strip() for v in cells.values()):
                raise ValueError('Unlabelled data row')
            continue
        votes = {key: signed_count(cells[col]) for col, key in columns.items()}
        metrics = {key: signed_count(cells[col], key == 'abstentions') for col, key in METRICS.items()}
        if (sum(votes.values()) != metrics['valid'] or
            metrics['valid'] + metrics['invalid'] != metrics['ballots'] or
            metrics['ballots'] + metrics['abstentions'] != metrics['electors']):
            raise ValueError('Row accounting mismatch')
        item = {'row': rownum, 'label': a or b, 'votes': votes, 'metrics': metrics}
        if a and b == '소계':
            finish()
            if a in parent_names:
                raise ValueError('Duplicate parent')
            parent_names.add(a)
            parent = item
            parents.append(item)
        elif a and not b:
            if a not in SPECIAL or a in special_names:
                raise ValueError('Unknown or duplicate special category')
            special_names.add(a)
            special.append(item)
        elif not a and b:
            if parent is None:
                raise ValueError('Orphan child')
            if any(x['parent_row'] == parent['row'] and x['label'] == b for x in children):
                raise ValueError('Duplicate child')
            item.update(parent_row=parent['row'], parent_label=parent['label'], mode=classify(b))
            children.append(item)
        else:
            raise ValueError('Unknown row layout')
    finish()
    if special_names != SPECIAL:
        raise ValueError('Missing special category')
    return parents, children, special

def build_report():
    archive = DIRECTORY / 'nec_2020_original_tables.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ZIP_SHA:
        raise ValueError('Source hash mismatch')
    seen, districts, members, output_children = set(), {}, [], []
    mode_rows, mode_votes = Counter(), Counter()
    parent_count = special_count = 0
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = display_name(info)
            if not name.startswith('지역구/') or not name.endswith('.xlsx'):
                continue
            content = bundle.read(info)
            key, jurisdiction, expected_votes, expected_metrics = read_table(content)
            if (key, jurisdiction) in seen:
                raise ValueError('Duplicate jurisdiction')
            seen.add((key, jurisdiction))
            rows = all_rows(content)
            header = dict(rows)[5]
            columns = {col: tuple(label.strip().split('\n')) for col, label in header.items()
                       if 5 <= column_number(col) <= 54 and label.strip()}
            if len(columns) != len(set(columns.values())) or set(columns.values()) != set(expected_votes):
                raise ValueError('Candidate header mismatch')
            for rownum, cells in rows:
                if rownum > 7 and (cells.get('A', '').strip() or cells.get('B', '').strip()):
                    for col, label in header.items():
                        if 5 <= column_number(col) <= 54 and not label.strip():
                            if signed_count(cells[col]) != 0:
                                raise ValueError('Unnamed candidate votes')
            parents, children, specials = parse_rows(rows, columns)
            for field, expected in [('votes', expected_votes), ('metrics', expected_metrics)]:
                if any(sum(x[field][k] for x in parents + specials) != v for k, v in expected.items()):
                    raise ValueError('Workbook total mismatch')
            source_hash = hashlib.sha256(content).hexdigest()
            members.append({'name': name, 'sha256': source_hash})
            parent_count += len(parents)
            special_count += len(specials)
            d = districts.setdefault(key, {'votes': Counter(), 'mode_valid': Counter(), 'valid': 0})
            if d['votes'] and set(d['votes']) != set(expected_votes):
                raise ValueError('District candidate mismatch')
            d['votes'].update(expected_votes)
            d['valid'] += expected_metrics['valid']
            for child in children + specials:
                mode = child.get('mode', 'district_special')
                mode_rows[mode] += 1
                mode_votes[mode] += child['metrics']['valid']
                d['mode_valid'][mode] += child['metrics']['valid']
                output_children.append({k: v for k, v in child.items() if k != 'votes'} | {
                    'mode': mode, 'province': key[0], 'district': key[1], 'jurisdiction': jurisdiction,
                    'source_member': name, 'source_sha256': source_hash,
                    'candidate_votes': [{'party_original': p, 'candidate': c, 'votes': v}
                                        for (p, c), v in child['votes'].items()]})
    expected_modes = {'internal_advance': 8925666, 'ordinary_station_label': 17012858,
                      'joint_station_label': 2523, 'district_special': 2800361}
    if (len(members), len(districts), parent_count, special_count) != (329, 253, 3485, 1645):
        raise ValueError('Coverage mismatch')
    if dict(mode_votes) != expected_modes or dict(mode_rows) != {
        'internal_advance': 3485, 'ordinary_station_label': 14329, 'joint_station_label': 1, 'district_special': 1645}:
        raise ValueError('National control mismatch')
    district_rows = []
    for key, d in sorted(districts.items()):
        if sum(d['mode_valid'].values()) != d['valid'] or sum(d['votes'].values()) != d['valid']:
            raise ValueError('District total mismatch')
        district_rows.append({'province': key[0], 'district': key[1], 'valid': d['valid'],
                              'mode_valid': dict(d['mode_valid'])})
    return {'status': 'PASS_BOOKKEEPING_ONLY', 'source_zip_sha256': ZIP_SHA,
            'parser_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'workbooks': len(members), 'district_count': len(districts), 'parent_subtotals': parent_count,
            'child_rows': len(output_children) - special_count, 'special_rows': special_count,
            'mode_rows': dict(mode_rows), 'mode_valid_votes': dict(mode_votes),
            'national_valid_votes': sum(mode_votes.values()), 'source_members': members,
            'districts': district_rows, 'children': output_children,
            'geography_approved': False, 'residence_assignment_verified': False,
            'allocation_generated': False, 'backtest_executed': False,
            'current_model_linked': False, 'party_support_used': False}

if __name__ == '__main__':
    result = build_report()
    target = Path(__file__).resolve().parents[1] / 'outputs/vote_modes_2020.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ['source_members', 'districts', 'children']}, ensure_ascii=False))
