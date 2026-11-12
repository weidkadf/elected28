#!/usr/bin/env python3
"""Download the newest NESDC '전국단위 선거여론조사결과 주요 데이터' workbook (board B0000025, posted weekly).

Writes data/nesdc/nesdc_major_data_national.xlsx and data/nesdc/nesdc_major_data_source.json only when the file content
changed. Exit code 0 = updated, 3 = unchanged, anything else = failure. Stdlib only (used by .github/workflows/update-polls.yml).
"""
import hashlib, html, io, json, re, sys, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://www.nesdc.go.kr'
LIST = BASE + '/portal/bbs/B0000025/list.do?menuNo=200500'
OUT = ROOT / 'data/nesdc/nesdc_major_data_national.xlsx'
META = ROOT / 'data/nesdc/nesdc_major_data_source.json'
UA = {'User-Agent': 'Mozilla/5.0 (compatible; election-model-updater)'}


def get(url, referer=None):
    h = dict(UA, **({'Referer': referer} if referer else {}))
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        return r.read()


def main():
    page = get(LIST).decode('utf-8', 'replace')
    # hrefs carry a ;jsessionid=... segment, so match up to the query and rebuild a clean URL
    posts = re.findall(r'href="/portal/bbs/B0000025/view\.do[^"?]*\?nttId=(\d+)[^"]*"[^>]*>\s*([^<]*?주요\s*데이터[^<]*?)\s*<', page)
    if not posts: sys.exit('no posts found on ' + LIST)
    ntt, title = max(posts, key=lambda p: int(p[0]))
    view_url = f'{BASE}/portal/bbs/B0000025/view.do?nttId={ntt}&menuNo=200500'
    view = get(view_url, LIST).decode('utf-8', 'replace')
    files = re.findall(r'href="(/portal/cmm/fms/FileDown\.do\?[^"]+)"[^>]*>\s*([^<]*?\.xlsx)\s*<', view)
    files = [f for f in files if '전국' in f[1]] or files
    if len(files) != 1: sys.exit(f'expected one national xlsx in post {ntt}, found {[f[1] for f in files]}')
    blob = get(BASE + html.unescape(files[0][0]), view_url)
    z = zipfile.ZipFile(io.BytesIO(blob))                     # raises if NESDC returned an error page instead of a workbook
    assert 'xl/workbook.xml' in z.namelist() and 'xl/sharedStrings.xml' in z.namelist()
    sha = hashlib.sha256(blob).hexdigest()
    if OUT.exists() and hashlib.sha256(OUT.read_bytes()).hexdigest() == sha:
        print('unchanged', ntt, title); sys.exit(3)
    OUT.write_bytes(blob)
    META.write_text(json.dumps({'post_nttId': int(ntt), 'post_title': title.strip(), 'post_url': view_url,
                                'file_name': files[0][1].strip(), 'sha256': sha, 'bytes': len(blob),
                                'fetched_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}, ensure_ascii=False, indent=1) + '\n',
                    encoding='utf-8')
    print('updated', ntt, title, sha[:12])


if __name__ == '__main__':
    main()
