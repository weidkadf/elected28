"""Validate manually reviewed book candidates; never enables model/history gates."""
from pathlib import Path
import csv,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
def validate():
    base=ROOT/'data/history_2020/nec_total_book'
    rows=json.loads((base/'candidate_transcription_890_891.json').read_text())
    report=json.loads((base/'candidate_crosscheck_890_891.json').read_text())
    assert hashlib.sha256((base/'total2020.pdf').read_bytes()).hexdigest()==report['source_pdf_sha256']
    source=ROOT/'data/history_2020/verified_candidates_2020.csv'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==report['verified_csv_sha256']
    actual=list(csv.DictReader(source.open(encoding='utf-8-sig')))
    districts=report['district_valid_votes']
    expected={(r['province'],r['district'],r['candidate']):r['votes'] for r in rows}
    selected=[r for r in actual if r['province']=='서울특별시' and r['district'] in districts]
    assert len(expected)==len(rows)==report['candidate_count']
    assert expected=={(r['province'],r['district'],r['candidate']):int(r['votes']) for r in selected}
    for d,v in districts.items():
        assert sum(r['votes'] for r in rows if r['district']==d)==v
        assert all(int(r['valid_votes'])==v for r in selected if r['district']==d)
    assert len(districts)==report['district_count']==13
    assert not report['geography_approved'] and not report['historical_available_on_approved'] and not report['current_model_input']
    print('PASS: 13 districts, 67 candidates; partial historical evidence only')
if __name__=='__main__':validate()
