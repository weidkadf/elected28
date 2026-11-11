#!/usr/bin/env python3
"""Canonical-source build, immutable old data, gated validated release."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

CHANGED = {'README.md','CHANGELOG.md','BACKLOG.md','UPDATE_PROTOCOL.md','model_notes.md',
           'poll_sources.md','state.json','scripts/render_summary.py','test_backtest_readiness.py','test_historical_580.py'}
NEW = {'data/history_polls/gallup_579_20240322.pdf','data/history_polls/gallup_579_source.html',
       'data/history_polls/gallup_579_frame_observations.json','test_historical_579.py',
       'scripts/validate_release_0_2_11.py','scripts/package_release_0_2_11.py',
       'outputs/research_check_20261019_0014.json'}
NEW_SOURCES = {p for p in NEW if p.startswith('data/history_polls/')}
GENERATED = {'outputs/historical_frame_inventory.json','outputs/backtest_readiness.json',
             'outputs/DISTRICT_STATUS.md','outputs/update_validation_20261019_0014.json'}
PRIOR_SHA = '32d8fdab3e155b64e6e6111699fd4a1f088199cfc2a10f015a32b8cccecda927'
SOURCE_SHA = '690176009970c6c45e37fee6a65af43c81635416915467a6177a369bd64ed74f'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior',type=Path,required=True)
    parser.add_argument('--working',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--new-sources', type=Path)
    parser.add_argument('--new-sources-sha256')
    args = parser.parse_args()
    assert bool(args.new_sources) == bool(args.new_sources_sha256)
    source_bytes = {}
    if args.new_sources:
        assert hashlib.sha256(args.new_sources.read_bytes()).hexdigest() == args.new_sources_sha256
        with zipfile.ZipFile(args.new_sources) as sources:
            assert sources.testzip() is None
            names = sources.namelist()
            assert len(names) == len(set(names)) == len(NEW_SOURCES)
            assert set(names) == NEW_SOURCES
            source_bytes = {name: sources.read(name) for name in names}
    assert hashlib.sha256(args.prior.read_bytes()).hexdigest() == PRIOR_SHA
    args.output.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='verified0211_',dir=args.output.parent.parent))
    with zipfile.ZipFile(args.prior) as prior:
        assert prior.testzip() is None
        assert all(n.startswith('election23/') and '..' not in Path(n).parts for n in prior.namelist())
        prior.extractall(staging)
    project = staging/'election23'
    for rel in sorted(CHANGED | NEW):
        target = project/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        if rel in source_bytes:
            target.write_bytes(source_bytes[rel])
        else:
            shutil.copyfile(args.working/rel,target)
    for command in ([sys.executable,'scripts/validate_historical_frames.py','--as-of','2026-10-19'],
                    [sys.executable,'scripts/build_backtest_readiness.py'],
                    [sys.executable,'scripts/render_summary.py'],
                    [sys.executable,'scripts/validate_release_0_2_11.py',str(args.prior.resolve())]):
        subprocess.run(command,cwd=project,check=True)
    # Whitelist every intentional replacement; all other prior entries stay byte-identical.
    with zipfile.ZipFile(args.prior) as prior:
        for name in prior.namelist():
            rel = name.removeprefix('election23/')
            if not name.endswith('/') and rel not in CHANGED | GENERATED:
                assert (project/rel).read_bytes() == prior.read(name),name
    with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for file in sorted(project.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                archive.write(file,file.relative_to(staging))
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        assert hashlib.sha256(archive.read('election23/data/history_2020/nec_2020_original_tables.zip')).hexdigest()==SOURCE_SHA
        audit=json.loads(archive.read('election23/outputs/update_validation_20261019_0014.json'))
        assert audit['status']=='PASS' and audit['unit_tests_total']==139
        assert json.loads(archive.read('election23/state.json'))['version']=='0.2.11'
    print(json.dumps({'status':'PASS','zip_path':str(args.output.resolve()),
                      'size_bytes':args.output.stat().st_size,
                      'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'staging':str(project)},ensure_ascii=False))


if __name__=='__main__':
    main()
