"""Package a verified release, preserving every prior file outside the allowlist."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CHANGED = {'README.md', 'CHANGELOG.md', 'BACKLOG.md', 'UPDATE_PROTOCOL.md',
           'state.json', 'scripts/render_summary.py', 'outputs/DISTRICT_STATUS.md'}
NEW = {'scripts/build_2020_vote_modes.py', 'test_vote_modes.py',
       'outputs/vote_modes_2020.json', 'scripts/validate_release_0_2_13.py',
       'scripts/package_release_0_2_13.py', 'outputs/update_validation_20261103.json',
       'outputs/research_check_20261103.json'}

def main():
    prior_path, output = map(Path, sys.argv[1:3])
    assert hashlib.sha256(prior_path.read_bytes()).hexdigest() == '9e0040b830e76ef1629867c11adbae63b3d30146ccd01e182bbf65dcf5abbc85'
    report = json.loads((ROOT/'outputs/update_validation_20261103.json').read_text())
    assert report['status'] == 'PASS' and report['unit_tests_total'] == 169
    assert all(report['checks'].values())
    with zipfile.ZipFile(prior_path) as prior:
        old = {n.removeprefix('election23/') for n in prior.namelist() if not n.endswith('/')}
        for name in old - CHANGED:
            assert (ROOT/name).read_bytes() == prior.read('election23/'+name), name
    current = {str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()
               and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    assert current == old | NEW, (current-(old|NEW), (old|NEW)-current)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(current):
            bundle.write(ROOT/name, 'election23/'+name)
    with zipfile.ZipFile(output) as bundle:
        assert bundle.testzip() is None
        for name in current:
            assert bundle.read('election23/'+name) == (ROOT/name).read_bytes()
    print(json.dumps({'file':str(output.resolve()), 'size':output.stat().st_size,
                      'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))

if __name__ == '__main__':
    main()
