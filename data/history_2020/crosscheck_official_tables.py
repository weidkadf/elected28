#!/usr/bin/env python3
"""Read-only XLSX extraction and exact, key-based comparison to recovered CSV.

No spreadsheet is edited. Only OOXML stored scalar values are read; formulas
in relevant cells fail closed. Sub-jurisdiction total rows are added once.
The independent representation is another NEC publication, not an independent
vote count. This check validates historical district totals, not 2024 geography.
"""
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
ZIP_SHA = '690176009970c6c45e37fee6a65af43c81635416915467a6177a369bd64ed74f'
METRICS = {'C': 'electors', 'D': 'ballots', 'BC': 'valid',
           'BD': 'invalid', 'BE': 'abstentions'}


def display_name(info):
    if info.flag_bits & 0x800:
        return info.filename
    return info.filename.encode('cp437').decode('cp949')


def column_number(column):
    value = 0
    for char in column:
        value = value * 26 + ord(char) - ord('A') + 1
    return value


def number(value):
    if not re.fullmatch(r'\d+', value):
        raise ValueError(f'Not a nonnegative integer: {value!r}')
    return int(value)


def read_table(content):
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        sheets = [n for n in book.namelist()
                  if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', n)]
        if sheets != ['xl/worksheets/sheet1.xml']:
            raise ValueError(f'Unexpected worksheets: {sheets}')
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            for si in ET.fromstring(book.read('xl/sharedStrings.xml')):
                strings.append(''.join(t.text or '' for t in si.findall('.//m:t', NS)))
        rows = {}
        for row in ET.fromstring(book.read(sheets[0])).findall('m:sheetData/m:row', NS):
            rownum = int(row.attrib['r'])
            if rownum > 7:
                break
            cells = {}
            for cell in row:
                if cell.find('m:f', NS) is not None:
                    raise ValueError('Formula in source header/total area')
                v = cell.find('m:v', NS)
                value = v.text if v is not None else ''
                if cell.attrib.get('t') == 's':
                    value = strings[int(value)]
                elif cell.attrib.get('t') == 'inlineStr':
                    value = ''.join(t.text or '' for t in cell.findall('.//m:t', NS))
                cells[re.sub(r'\d+', '', cell.attrib['r'])] = value
            rows[rownum] = cells
    if rows[1].get('A') not in {'개표상황(투표구별)', '개표단위별 개표결과'} or rows[7].get('A') != '합계':
        raise ValueError('Unexpected title or missing total row')
    identifiers = re.findall(r'\[([^\[\]]+)\]', rows[3]['A'])
    if len(identifiers) != 4 or identifiers[0] != '국회의원선거':
        raise ValueError(f'Not an identified general-election district: {identifiers}')
    if rows[5].get('BC') != '계' or rows[4].get('C') != '선거인수':
        raise ValueError('Unexpected source columns')
    totals = {name: number(rows[7][col]) for col, name in METRICS.items()}
    candidates = {}
    for col, label in rows[5].items():
        if not 5 <= column_number(col) <= 54:
            continue
        value = number(rows[7][col])
        if not label.strip():
            if value:
                raise ValueError('Nonzero vote in unnamed candidate column')
            continue
        parts = label.strip().split('\n')
        if len(parts) != 2 or not all(parts):
            raise ValueError(f'Ambiguous candidate label: {label!r}')
        key = tuple(parts)
        if key in candidates:
            raise ValueError('Duplicate candidate')
        candidates[key] = value
    if sum(candidates.values()) != totals['valid']:
        raise ValueError('Candidate totals != valid votes')
    if totals['valid'] + totals['invalid'] != totals['ballots']:
        raise ValueError('Valid + invalid != ballots')
    if totals['ballots'] + totals['abstentions'] != totals['electors']:
        raise ValueError('Ballots + abstentions != electorate')
    return tuple(identifiers[1:3]), identifiers[3], candidates, totals


def crosscheck():
    archive = ROOT / 'nec_2020_original_tables.zip'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == ZIP_SHA
    official = {}
    manifest = []
    excluded = collections.Counter()
    jurisdictions = set()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = display_name(info)
            if not name.endswith('.xlsx'):
                continue
            if not name.startswith('지역구/'):
                excluded[name.split('/')[0]] += 1
                continue
            content = bundle.read(info)
            try:
                key, jurisdiction, votes, totals = read_table(content)
            except (ValueError, KeyError, AssertionError) as exc:
                raise ValueError(f'{name}: {exc}') from exc
            assert (key, jurisdiction) not in jurisdictions, 'Duplicate jurisdiction'
            jurisdictions.add((key, jurisdiction))
            d = official.setdefault(key, {'votes': collections.Counter(),
                                         'totals': collections.Counter(), 'files': []})
            if d['files']:
                assert set(d['votes']) == set(votes), 'Candidate mismatch across district parts'
            d['votes'].update(votes)
            d['totals'].update(totals)
            d['files'].append(name)
            manifest.append({'archive_member': name, 'province': key[0], 'district': key[1],
                             'jurisdiction': jurisdiction, 'sha256': hashlib.sha256(content).hexdigest(),
                             'title_cell': 'A3', 'candidate_header_row': 5, 'total_row': 7,
                             'candidate_votes': [{'party': p, 'candidate': c, 'votes': n}
                                                 for (p, c), n in votes.items()], 'totals': totals})
    with (ROOT / 'reconstructed_candidates_QUARANTINED.csv').open(encoding='utf-8-sig', newline='') as f:
        recovered_rows = list(csv.DictReader(f))
    with (ROOT / 'reconstructed_district_totals_QUARANTINED.csv').open(encoding='utf-8-sig', newline='') as f:
        recovered_totals = {(r['province'], r['district']): r for r in csv.DictReader(f)}
    recovered = {}
    for r in recovered_rows:
        key = r['province'], r['district']
        vote_key = r['party_original'], r['candidate']
        d = recovered.setdefault(key, {})
        assert vote_key not in d, 'Duplicate recovered candidate'
        d[vote_key] = int(r['votes'])
    details = []
    for key in sorted(set(official) | set(recovered) | set(recovered_totals)):
        errors = []
        a, b, total = official.get(key), recovered.get(key), recovered_totals.get(key)
        if a is None or b is None or total is None:
            errors.append('missing_district')
        else:
            if set(a['votes']) != set(b) or a['votes'] != b:
                errors.append('candidate_party_name_or_votes_mismatch')
            for metric in METRICS.values():
                if a['totals'][metric] != int(total[metric]):
                    errors.append(metric + '_mismatch')
            if len(a['votes']) != int(total['candidate_count']):
                errors.append('candidate_count_mismatch')
            if list(a['votes'].values()).count(max(a['votes'].values())) != 1:
                errors.append('official_winner_not_unique')
            aw = max(a['votes'], key=a['votes'].get)
            bw = max(b, key=b.get)
            if aw != bw:
                errors.append('winner_mismatch')
            for r in (r for r in recovered_rows if (r['province'], r['district']) == key):
                if int(r['valid_votes']) != a['totals']['valid']:
                    errors.append('candidate_denominator_mismatch')
                if int(r['winner_reconstructed']) != int((r['party_original'], r['candidate']) == aw):
                    errors.append('winner_flag_mismatch')
        details.append({'province': key[0], 'district': key[1], 'status': 'PASS' if not errors else 'FAIL',
                        'errors': sorted(set(errors)), 'official_members': a['files'] if a else []})
    passed = len(details) == 253 and all(not d['errors'] for d in details)
    report = {'check_version': '1.0.0', 'verified_date': '2026-10-16',
              'status': 'PASS' if passed else 'FAIL',
              'official_zip_sha256': ZIP_SHA, 'official_workbooks': len(manifest),
              'source_page': 'https://www.nec.go.kr/site/nec/ex/bbs/View.do?bcIdx=15052&cbIdx=1129',
              'parser_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'districts_checked': len(details), 'districts_passed': sum(not d['errors'] for d in details),
              'candidate_labels_checked': len(recovered_rows),
              'excluded_xlsx_by_category': dict(excluded),
              'historical_district_totals_verified': passed,
              'model_eligible': False,
              'remaining_gates': ['2020_to_2024_boundary_crosswalk',
                                  'poll_history_and_time_split_backtest', 'candidate_party_mapping'],
              'scope_note': 'NEC alternative official XLSX representation, not independent ballot recount. '
                            'District totals only; not every polling-station row or withdrawn-candidate registry.',
              'raw_files_unchanged': True, 'district_checks': details}
    (ROOT / 'official_table_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'independent_crosscheck_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if passed:
        verified = [{**r, 'validation_status': 'OFFICIAL_ALTERNATIVE_TABLE_DISTRICT_TOTALS_VERIFIED',
                     'geography': '2020_original_boundaries',
                     'current_model_eligible': 'false'} for r in recovered_rows]
        with (ROOT / 'verified_candidates_2020.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(verified[0]))
            writer.writeheader()
            writer.writerows(verified)
    print(json.dumps({k: v for k, v in report.items() if k != 'district_checks'}, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    crosscheck()
