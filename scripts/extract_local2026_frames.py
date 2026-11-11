#!/usr/bin/env python3
"""Gallup 662/663/664 (2026-04-28 .. 05-21) '지방선거 결과 기대' -> frame observation files (v0.4.0).

Wording differs slightly from the general-election item: '여당 후보가 많이 당선돼야 한다 / 야당 후보가 많이
당선돼야 한다' without the '현 정부 지원/견제 위해' clause. Stored with wording_note; shares keep the
archive labels 정부지원(=여당 다수) / 정부견제(=야당 다수) so the same aggregator reads them.
Requires pdftotext.
"""
from __future__ import annotations
import hashlib, json, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HP = ROOT / 'data' / 'history_polls'
WAVES = {'662': ('gallup_662_20260501.pdf', '2026-04-28', '2026-04-30', '2026-05-01'),
         '663': ('gallup_663_20260515.pdf', '2026-05-12', '2026-05-14', '2026-05-15'),
         '664': ('gallup_664_20260522.pdf', '2026-05-19', '2026-05-21', '2026-05-22')}
SCOPES = ['서울', '인천/경기', '강원', '대전/세종/충청', '광주/전라', '대구/경북', '부산/울산/경남', '제주']


def main():
    for w, (pdf, start, end, pub) in WAVES.items():
        p = HP / pdf
        lines = subprocess.run(['pdftotext', '-layout', str(p), '-'], capture_output=True, text=True, check=True).stdout.splitlines()
        i = next(k for k, l in enumerate(lines) if '조사완료' in l and '지방선거 결과 기대' in l)
        sec = lines[i:i + 20]
        polls = []
        for scope, name in [('national', '전체')] + [(s, s) for s in SCOPES]:
            row = None
            for l in sec:
                m = re.search(re.escape(name) + r'\s+([\d,]+)\s+([\d,]+)\s+(?:(\d+)%\s+(\d+)%\s+(\d+)%|-\s+-\s+-)', l)
                if m:
                    row = m
                    break
            if row is None:
                raise SystemExit(f'{w}: row {name} not found')
            sup = row.group(3)
            polls.append({'poll_id': f'gallup_{w}_frame_{scope}', 'pollster': '한국갤럽', 'scope': scope,
                          'fieldwork_start': start, 'fieldwork_end': end, 'published_at': pub,
                          'sample_size': int(row.group(1).replace(',', '')), 'weighted_sample_size': int(row.group(2).replace(',', '')),
                          'governing_party': '더불어민주당', 'opposition_party': '국민의힘',
                          'democratic_coordinate_component': '정부지원',
                          'shares': {} if sup is None else {'정부지원': int(sup) / 100, '정부견제': int(row.group(4)) / 100,
                                                            '모름/응답거절': int(row.group(5)) / 100}})
        out = {'schema_version': 'gallup_frame_observations_local_1', 'target_election': '2026-06-03 제9회 전국동시지방선거',
               'question_exact': '지방선거와 관련해 다음 중 어느 주장에 더 동의하십니까? 여당 후보가 많이 당선돼야 한다 / 야당 후보가 많이 당선돼야 한다',
               'wording_note': 'no 정부 지원/견제 clause; treated as the same class with this caveat',
               'source_pdf': pdf, 'source_pdf_sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
               'source_url': f'https://www.gallup.co.kr/dir/GallupKoreaDaily/GallupKoreaDailyOpinion_{w}({pub.replace("-", "")}).pdf',
               'polls': polls}
        (HP / f'gallup_{w}_local_frame.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(w, [(x['scope'], x['shares'].get('정부지원'), x['shares'].get('정부견제')) for x in polls])


if __name__ == '__main__':
    main()
