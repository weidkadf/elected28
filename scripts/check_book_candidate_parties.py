"""Check original 2020 party labels without successor mapping or polling inputs."""
import csv,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def validate():
    d=ROOT/'data/history_2020/nec_total_book'
    previous=json.loads((d/'candidate_crosscheck_890_891.json').read_text())
    source=ROOT/'data/history_2020/verified_candidates_2020.csv'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==previous['verified_csv_sha256']
    assert hashlib.sha256((d/'total2020.pdf').read_bytes()).hexdigest()==previous['source_pdf_sha256']
    rows=json.loads((d/'candidate_party_transcription_890_891.json').read_text())
    districts={x['district'] for x in rows}
    expected={(x['province'],x['district'],x['candidate']):(x['party_original'],x['votes']) for x in rows}
    actual=list(csv.DictReader(source.open(encoding='utf-8-sig')))
    observed={(x['province'],x['district'],x['candidate']):(x['party_original'],int(x['votes'])) for x in actual if x['province']=='서울특별시' and x['district'] in districts}
    assert len(expected)==len(rows)==67 and len(districts)==13
    assert expected==observed
    print('PASS: 13 districts, 67 original party labels and votes; no successor mapping')
if __name__=='__main__':validate()
