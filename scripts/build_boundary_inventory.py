#!/usr/bin/env python3
"""Extract ruled PDF cells and compare statutory text, never infer vote weights.

Whitespace and middle-dot typography are ignored for text comparison only.
Same text is not proof of polygon equivalence: administrative boundaries can
change without changing names. No output here is authorized as a vote crosswalk.
"""
import collections
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import unicodedata

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'data/boundary_research'
PROVINCE_ALIASES = {'강원도': '강원특별자치도', '전라북도': '전북특별자치도'}
EXPECTED = {2020: 253, 2024: 254}


def compact(value):
    # U+2024 ONE DOT LEADER becomes a period under NFKC; harmonize it first.
    value = (value or '').translate(str.maketrans({'․': '·', 'ㆍ': '·', '∙': '·'}))
    value = unicodedata.normalize('NFKC', value)
    return re.sub(r'\s+', '', value)


def parse_source(source):
    path = ROOT / source['local_pdf']
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != source['sha256']:
        raise ValueError('Official PDF source hash changed')
    districts = []
    province = None
    declared = {}
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            if not tables:
                raise ValueError(f'No ruled table on page {page_number}')
            for table_number, table in enumerate(tables, 1):
                for row_number, row in enumerate(table, 1):
                    if len(row) != 2:
                        raise ValueError(f'Unexpected column count on page {page_number}')
                    left, right = row
                    title = compact(left)
                    if not title and not compact(right):
                        continue
                    if title == '선거구명' and compact(right) == '선거구역':
                        continue
                    match = re.fullmatch(r'(.+)\(지역구:(\d+)\)', title)
                    if match:
                        province = match[1]
                        if province in declared:
                            raise ValueError('Repeated province heading')
                        declared[province] = int(match[2])
                        continue
                    if not province or not title.endswith('선거구') or not compact(right):
                        raise ValueError(f'Unresolved cell on page {page_number}: {row!r}')
                    districts.append({'year': source['year'], 'province_original': province,
                                      'province': PROVINCE_ALIASES.get(province, province),
                                      'district_name': title[:-3], 'title_raw': left,
                                      'statutory_area_raw': right,
                                      'statutory_area_compact': compact(right),
                                      'pdf_page_1based': page_number, 'table_1based': table_number,
                                      'table_row_1based': row_number, 'source_url': source['url'],
                                      'source_pdf_sha256': digest})
    counts = collections.Counter(d['province_original'] for d in districts)
    if counts != declared or sum(declared.values()) != EXPECTED[source['year']]:
        raise ValueError(f'Province/total coverage mismatch: {counts} versus {declared}')
    keys = [(d['province'], d['district_name']) for d in districts]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate statutory district key')
    return districts, declared


def historical_keys(year):
    name = 'data/districts_2024.csv' if year == 2024 else 'data/history_2020/reconstructed_district_totals_QUARANTINED.csv'
    with (ROOT / name).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if year == 2024:
        return {(r['region'], r['district_name']) for r in rows}
    return {(PROVINCE_ALIASES.get(r['province'], r['province']), r['district']) for r in rows}


def build_inventory():
    manifest = json.loads((DIRECTORY/'source_manifest.json').read_text())
    parsed, province_counts = {}, {}
    for source in manifest:
        year = source['year']
        if year not in EXPECTED or year in parsed:
            raise ValueError('Unknown or duplicate source year')
        parsed[year], province_counts[year] = parse_source(source)
    if set(parsed) != set(EXPECTED):
        raise ValueError('Both election boundary sources required')
    for year in EXPECTED:
        observed = {(d['province'], d['district_name']) for d in parsed[year]}
        expected = historical_keys(year)
        if observed != expected:
            raise ValueError(f'{year} district identity mismatch: missing={expected-observed}; extra={observed-expected}')
    old = {(d['province'], d['district_name']): d for d in parsed[2020]}
    with (ROOT/'data/districts_2024.csv').open(encoding='utf-8-sig', newline='') as f:
        ids = {(r['region'], r['district_name']): r['district_id'] for r in csv.DictReader(f)}
    inventory = []
    for row in parsed[2024]:
        key = row['province'], row['district_name']
        prior = old.get(key)
        if prior is None:
            status = 'no_same_name_predecessor_review_required'
        elif row['statutory_area_compact'] == prior['statutory_area_compact']:
            status = 'same_name_same_statutory_text_geometry_unverified'
        else:
            status = 'same_name_statutory_text_diff_review_required'
        inventory.append({'district_id': ids[key],
                          'province': row['province'], 'district_name': row['district_name'],
                          'review_status': status, 'statutory_2024': row,
                          'same_name_statutory_2020': prior,
                          'vote_transfer_weight': None, 'crosswalk_eligible': False,
                          'reason': 'Text inventory only; administrative changes and polygon/vote-unit mapping not verified.'})
    counts = dict(collections.Counter(r['review_status'] for r in inventory))
    summary = {'inventory_version': '1.0.0', 'verified_date': '2026-10-17',
               'status': 'STATUTORY_ROW_INVENTORY_PASS_CROSSWALK_NOT_READY',
               'parser': 'pdfplumber ruled-table cell extraction',
               'pdfplumber_version': importlib.metadata.version('pdfplumber'),
               'extracted_counts': {str(y): len(v) for y, v in parsed.items()},
               'province_counts_match_source_headings': True,
               'district_keys_match_historical_vote_files': True,
               'comparison_status_counts': counts,
               '2024_districts_reviewed': len(inventory), 'crosswalk_eligible_districts': 0,
               'vote_transfer_weights_estimated': False, 'model_inputs_modified': False,
               'province_alias_policy': PROVINCE_ALIASES,
               'normalization_policy': 'NFKC, whitespace removal and middle-dot glyph harmonization only; no administrative-unit equivalence assumed',
               'limitations': ['Matching statutory text does not prove unchanged geometry.',
                              'Text differences may include administrative renaming/splitting, not only electoral moves.',
                              'No areal/population/vote allocation weights or party vote redistribution.'],
               'source_pdf_sha256': {str(s['year']): s['sha256'] for s in manifest},
               'parser_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (DIRECTORY/'statutory_district_rows.json').write_text(json.dumps(parsed, ensure_ascii=False, indent=2)+'\n')
    (DIRECTORY/'boundary_review_254.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2)+'\n')
    (DIRECTORY/'boundary_inventory_report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return parsed, inventory, summary


if __name__ == '__main__':
    build_inventory()
