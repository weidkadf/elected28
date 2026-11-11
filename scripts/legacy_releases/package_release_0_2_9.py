#!/usr/bin/env python3
"""Build from canonical 0.2.8 sources; upload only after successful validation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

CHANGED = {'README.md', 'CHANGELOG.md', 'BACKLOG.md', 'model_notes.md', 'UPDATE_PROTOCOL.md',
           'state.json', 'scripts/render_summary.py', 'outputs/DISTRICT_STATUS.md', 'poll_sources.md',
           'scripts/validate_historical_frames.py', 'outputs/historical_frame_inventory.json'}
NEW = {'scripts/build_backtest_readiness.py', 'test_backtest_readiness.py',
       'outputs/research_check_20261018_0705.json',
       'scripts/validate_release_0_2_9.py', 'scripts/package_release_0_2_9.py'}

PRIOR_SHA = 'ea4eb988253ba1e97ddba606dbf823078ec991ccf5968da3dddafe5f1bad199b'
SOURCE_SHA = '690176009970c6c45e37fee6a65af43c81635416915467a6177a369bd64ed74f'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--working', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.prior.read_bytes()).hexdigest() == PRIOR_SHA, 'prior archive integrity failed'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='verified029_', dir=args.output.parent.parent))
    with zipfile.ZipFile(args.prior) as prior:
        assert prior.testzip() is None
        assert all(n.startswith('election23/') and '..' not in Path(n).parts for n in prior.namelist())
        prior.extractall(staging)
        existing = {n.removeprefix('election23/') for n in prior.namelist()}
    project = staging / 'election23'
    for file in sorted(args.working.rglob('*')):
        if not file.is_file():
            continue
        rel = file.relative_to(args.working)
        if '__pycache__' in rel.parts or any(p.startswith('.') for p in rel.parts) or file.suffix == '.pyc':
            continue
        if rel.as_posix() in CHANGED or rel.as_posix() in NEW:
            target = project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
    assert all((project / name).is_file() for name in NEW)
    subprocess.run([sys.executable, 'scripts/build_backtest_readiness.py'], cwd=project, check=True)
    subprocess.run([sys.executable, 'scripts/render_summary.py'], cwd=project, check=True)
    subprocess.run([sys.executable, 'scripts/validate_release_0_2_9.py', str(args.prior.resolve())], cwd=project, check=True)
    with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as result:
        for file in sorted(project.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                result.write(file, file.relative_to(staging))
    with zipfile.ZipFile(args.output) as result:
        assert result.testzip() is None
        assert hashlib.sha256(result.read('election23/data/history_2020/nec_2020_original_tables.zip')).hexdigest() == SOURCE_SHA
        assert json.loads(result.read('election23/outputs/update_validation_20261018_0705.json'))['unit_tests_total'] == 123
    print(json.dumps({'status': 'PASS', 'zip_path': str(args.output.resolve()), 'size_bytes': args.output.stat().st_size,
                      'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(), 'staging': str(project)}, ensure_ascii=False))


if __name__ == '__main__':
    main()


