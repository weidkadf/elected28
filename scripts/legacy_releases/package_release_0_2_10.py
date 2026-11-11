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
           'poll_sources.md','state.json','scripts/render_summary.py','test_backtest_readiness.py'}
NEW = {'data/history_polls/gallup_580_20240329.pdf','data/history_polls/gallup_580_source.html',
       'data/history_polls/gallup_580_frame_observations.json','test_historical_580.py',
       'scripts/validate_release_0_2_10.py','scripts/package_release_0_2_10.py',
       'outputs/research_check_20261018_1237.json'}
GENERATED = {'outputs/historical_frame_inventory.json','outputs/backtest_readiness.json',
             'outputs/DISTRICT_STATUS.md','outputs/update_validation_20261018_1237.json'}
PRIOR_SHA = '36aabc67a50786542f20ba603053a609bf323f284ab4562fd016a9bcebdc41de'
SOURCE_SHA = '690176009970c6c45e37fee6a65af43c81635416915467a6177a369bd64ed74f'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior',type=Path,required=True)
    parser.add_argument('--working',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.prior.read_bytes()).hexdigest() == PRIOR_SHA
    args.output.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='verified0210_',dir=args.output.parent.parent))
    with zipfile.ZipFile(args.prior) as prior:
        assert prior.testzip() is None
        assert all(n.startswith('election23/') and '..' not in Path(n).parts for n in prior.namelist())
        prior.extractall(staging)
    project = staging/'election23'
    for rel in sorted(CHANGED | NEW):
        target = project/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(args.working/rel,target)
    for command in ([sys.executable,'scripts/validate_historical_frames.py','--as-of','2026-10-18'],
                    [sys.executable,'scripts/build_backtest_readiness.py'],
                    [sys.executable,'scripts/render_summary.py'],
                    [sys.executable,'scripts/validate_release_0_2_10.py',str(args.prior.resolve())]):
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
        audit=json.loads(archive.read('election23/outputs/update_validation_20261018_1237.json'))
        assert audit['status']=='PASS' and audit['unit_tests_total']==131
        assert json.loads(archive.read('election23/state.json'))['version']=='0.2.10'
    print(json.dumps({'status':'PASS','zip_path':str(args.output.resolve()),
                      'size_bytes':args.output.stat().st_size,
                      'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'staging':str(project)},ensure_ascii=False))


if __name__=='__main__':
    main()
