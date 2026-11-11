#!/usr/bin/env python3
"""Read NEC XLSX subtotals once; separate named wards from unlocated votes.

No workbooks, originals, election model inputs or scenarios are modified.
Special categories retain original district/candidate identity. They are not
proportionally allocated to wards or new districts.
"""
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT/'data/history_2020'
sys.path.insert(0, str(DIRECTORY))
from crosscheck_official_tables import NS, ZIP_SHA, METRICS, display_name, read_table, column_number


def all_rows(content):
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        strings = [''.join(t.text or '' for t in si.findall('.//m:t',NS))
                   for si in ET.fromstring(book.read('xl/sharedStrings.xml'))]
        rows = []
        for row in ET.fromstring(book.read('xl/worksheets/sheet1.xml')).findall('m:sheetData/m:row',NS):
            cells = {}
            for c in row:
                if c.find('m:f',NS) is not None:
                    raise ValueError('Formula in official scalar table')
                v = c.find('m:v',NS)
                value = v.text if v is not None else ''
                if c.attrib.get('t')=='s':
                    value = strings[int(value)]
                cells[re.sub(r'\d+','',c.attrib['r'])] = value
            rows.append((int(row.attrib['r']),cells))
    return rows


def signed_count(value, negative_allowed=False):
    if not re.fullmatch(r'-?\d+' if negative_allowed else r'\d+', value):
        raise ValueError(f'Unexpected vote/count value: {value!r}')
    return int(value)


def build_inventory():
    archive = DIRECTORY/'nec_2020_original_tables.zip'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==ZIP_SHA
    units, districts, seen = [], {}, set()
    workbook_count = 0
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = display_name(info)
            if not name.startswith('지역구/') or not name.endswith('.xlsx'):
                continue
            workbook_count += 1
            content = bundle.read(info)
            key,jurisdiction,total_votes,totals = read_table(content)
            assert (key,jurisdiction) not in seen
            seen.add((key,jurisdiction))
            rows = all_rows(content)
            header = dict(rows)[5]
            candidate_columns = {col:tuple(label.strip().split('\n')) for col,label in header.items()
                                 if 5<=column_number(col)<=54 and label.strip()}
            assert set(candidate_columns.values())==set(total_votes)
            selected_votes, selected_totals = collections.Counter(),collections.Counter()
            d = districts.setdefault(key, {'province':key[0],'district':key[1],
                                          'total_votes':collections.Counter(),'ward_votes':collections.Counter(),
                                          'unlocated_votes':collections.Counter(),'totals':collections.Counter(),
                                          'ward_valid':0,'unlocated_valid':0,'ward_rows':0,'unlocated_rows':0})
            d['total_votes'].update(total_votes)
            d['totals'].update(totals)
            for rownum,cells in rows:
                if rownum<=7 or not cells.get('A','').strip():
                    continue  # No total row or child polling-station double count.
                label = cells['A'].strip()
                b = cells.get('B','').strip()
                if b=='소계':
                    kind = 'named_eupmyeondong_subtotal'
                elif not b:
                    kind = 'district_level_unlocated_category'
                else:
                    raise ValueError(f'Unresolved labelled row: {name}:{rownum}: {label}/{b}')
                votes = {candidate:signed_count(cells[col]) for col,candidate in candidate_columns.items()}
                counts = {metric:signed_count(cells[col],metric=='abstentions') for col,metric in METRICS.items()}
                assert sum(votes.values())==counts['valid']
                assert counts['valid']+counts['invalid']==counts['ballots']
                assert counts['ballots']+counts['abstentions']==counts['electors']
                for col,label_value in header.items():
                    if 5<=column_number(col)<=54 and not label_value.strip():
                        assert signed_count(cells[col])==0
                selected_votes.update(votes)
                selected_totals.update(counts)
                bucket = 'ward' if kind=='named_eupmyeondong_subtotal' else 'unlocated'
                d[bucket+'_votes'].update(votes)
                d[bucket+'_valid'] += counts['valid']
                d[bucket+'_rows'] += 1
                units.append({'province':key[0],'district':key[1],'jurisdiction':jurisdiction,
                              'row_kind':kind,'unit_label':label,'totals':counts,
                              'candidate_votes':[{'party_original':p,'candidate':c,'votes':n} for (p,c),n in votes.items()],
                              'source_member':name,'source_row_1based':rownum,
                              'source_member_sha256':hashlib.sha256(content).hexdigest(),
                              'target_2024_district':None,'crosswalk_eligible':False})
            assert selected_totals==totals, f'Total reconciliation failed: {name}'
            assert set(selected_votes)==set(total_votes) and selected_votes==total_votes, name
    with (DIRECTORY/'verified_candidates_2020.csv').open(encoding='utf-8-sig',newline='') as f:
        gold = list(csv.DictReader(f))
    expected = collections.defaultdict(dict)
    for r in gold:
        expected[(r['province'],r['district'])][(r['party_original'],r['candidate'])] = int(r['votes'])
    assert set(districts)==set(expected) and len(districts)==253 and workbook_count==329
    readiness = []
    for key,d in sorted(districts.items()):
        assert dict(d['total_votes'])==expected[key]
        assert d['ward_valid']+d['unlocated_valid']==d['totals']['valid']
        assert d['ward_votes']+d['unlocated_votes']==d['total_votes']
        readiness.append({'province':key[0],'district':key[1],
                          'valid_votes':d['totals']['valid'],'named_ward_valid_votes':d['ward_valid'],
                          'unlocated_valid_votes':d['unlocated_valid'],
                          'unlocated_valid_fraction':d['unlocated_valid']/d['totals']['valid'],
                          'named_ward_rows':d['ward_rows'],'unlocated_category_rows':d['unlocated_rows'],
                          'candidate_partition':[{'party_original':p,'candidate':c,'total':n,
                                                  'named_ward':d['ward_votes'][(p,c)],
                                                  'unlocated':d['unlocated_votes'][(p,c)]} for (p,c),n in d['total_votes'].items()],
                          'crosswalk_eligible':False,
                          'blocked_by':['2020_to_2024_geographic_equivalence_unverified',
                                        'district_level_unlocated_votes_not_allocated']})
    categories = collections.Counter()
    for u in units:
        if u['row_kind']=='district_level_unlocated_category':
            categories[u['unit_label']] += u['totals']['valid']
    report = {'inventory_version':'1.0.0','verified_date':'2026-10-17','status':'PASS',
              'official_workbooks_checked':workbook_count,'districts_reconciled':len(readiness),
              'named_ward_rows':sum(r['named_ward_rows'] for r in readiness),
              'unlocated_category_rows':sum(r['unlocated_category_rows'] for r in readiness),
              'national_valid_votes':sum(r['valid_votes'] for r in readiness),
              'named_ward_valid_votes':sum(r['named_ward_valid_votes'] for r in readiness),
              'unlocated_valid_votes':sum(r['unlocated_valid_votes'] for r in readiness),
              'unlocated_category_valid_votes':dict(categories),
              'districts_with_positive_unlocated_votes':sum(r['unlocated_valid_votes']>0 for r in readiness),
              'candidate_totals_match_verified_2020':True,'model_inputs_modified':False,
              'allocation_weights_created':False,'crosswalk_eligible_districts':0,
              'source_zip_sha256':ZIP_SHA,'parser_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'limitations':['Named subtotal describes 2020 administrative units, not verified 2024 geometry.',
                             'Unlocated categories remain in original district/candidate identities.',
                             'This is bookkeeping partition, not electoral transfer or calibrated forecast.']}
    (DIRECTORY/'ward_units_2020.json').write_text(json.dumps(units,ensure_ascii=False,indent=2)+'\n')
    (DIRECTORY/'ward_readiness_253.json').write_text(json.dumps(readiness,ensure_ascii=False,indent=2)+'\n')
    (DIRECTORY/'ward_inventory_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return units,readiness,report


if __name__=='__main__':
    build_inventory()
