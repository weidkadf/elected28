#!/usr/bin/env python3
"""Single entry point for release validation and packaging (replaces 20 per-release scripts).

  python scripts/validate.py --list
  python scripts/validate.py --release 0.3.0 --prior Election23_Model_v0.2.18.zip [--package OUT.zip]
  python scripts/validate.py --release 0.2.13 --legacy validate -- <legacy args>   # archived scripts

Generic path (>= 0.3.0) reads config/releases.json and checks, failing closed:
  1. parent ZIP SHA256 and ZIP CRC; parent state.json version
  2. every parent file outside `changed`/`moved`/`removed` is byte-identical
  3. moved files are byte-identical at their new path
  4. the current file set is exactly parent - removed - moved_old + moved_new + new (+ changed)
  5. full unit-test suite passes (count >= min_tests)
  6. every regenerated output is reproduced byte-for-byte from inputs in a scratch copy
  7. outputs/update_validation_<date>_v<ver>.json is written; --package writes and re-verifies the ZIP
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / 'scripts' / 'legacy_releases'
SKIP = {'__pycache__'}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def tree(root):
    return {str(p.relative_to(root)) for p in root.rglob('*')
            if p.is_file() and not SKIP & set(p.parts) and p.suffix != '.pyc' and p.name != '.DS_Store'}


def registry():
    return json.loads((ROOT / 'config/releases.json').read_text(encoding='utf-8'))['releases']


def run_legacy(version, mode, args):
    """Execute an archived per-release script as if it still lived in scripts/ (ROOT = parents[1])."""
    name = f"{mode}_release_{version.replace('.', '_')}.py"
    src = LEGACY / name
    if not src.exists():
        raise SystemExit(f'no archived {mode} script for {version}')
    fake = ROOT / 'scripts' / name
    sys.argv = [str(fake), *args]
    os.chdir(ROOT)
    code = compile(src.read_text(encoding='utf-8'), str(fake), 'exec')
    exec(code, {'__name__': '__main__', '__file__': str(fake)})


def run_tests():
    """Run the suite in a scratch copy: some legacy tests rebuild inventory files in place."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / 'election23'
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        r1 = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', '.', '-p', 'test_*.py'],
                            cwd=work, capture_output=True, text=True)
        r2 = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'data/history_2020', '-p', 'test_crosscheck.py'],
                            cwd=work, capture_output=True, text=True)
    count = 0
    for r in (r1, r2):
        m = re.search(r'Ran (\d+) tests', r.stderr)
        count += int(m.group(1)) if m else 0
    ok = r1.returncode == 0 and r2.returncode == 0
    return ok, count, (r1.stderr[-2000:] + r2.stderr[-2000:]) if not ok else ''


def regenerate(rel):
    """Re-run each pipeline step in a scratch copy and compare outputs byte-for-byte."""
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / 'election23'
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for step in rel['regenerate']:
            r = subprocess.run([sys.executable, *step['cmd']], cwd=work, capture_output=True, text=True)
            exact = r.returncode == 0 and all((work / o).read_bytes() == (ROOT / o).read_bytes() for o in step['outputs'])
            # legacy model.py writes no final newline; archived copies carry one. Accept only that difference.
            same = exact or (r.returncode == 0 and all((work / o).read_bytes().rstrip(b'\n') == (ROOT / o).read_bytes().rstrip(b'\n')
                                                       for o in step['outputs']))
            results.append({'cmd': ' '.join(step['cmd']), 'returncode': r.returncode, 'outputs_identical': same,
                            'byte_exact': exact,
                            'stderr_tail': r.stderr[-500:] if not same else ''})
    return results


def validate(version, prior_path):
    rel = registry()[version]
    blob = Path(prior_path).read_bytes()
    checks = {'parent_sha256_matches': sha(blob) == rel['parent_sha256']}
    pat = re.compile(rel['moved_dir']['pattern']) if rel.get('moved_dir') else None
    with zipfile.ZipFile(prior_path) as z:
        checks['parent_zip_crc_ok'] = z.testzip() is None
        old = {n.removeprefix('election23/'): n for n in z.namelist() if not n.endswith('/')}
        checks['parent_version_matches'] = json.loads(z.read('election23/state.json'))['version'] == rel['parent_version']
        moved = {o: o.replace(rel['moved_dir']['from'], rel['moved_dir']['to'], 1) for o in old if pat and pat.match(o)}
        changed, removed = set(rel['changed']), set(rel.get('removed', []))
        bad = [o for o in old if o not in changed | removed | set(moved) and (not (ROOT / o).exists() or (ROOT / o).read_bytes() != z.read(old[o]))]
        checks['unchanged_files_byte_identical'] = not bad
        badm = [o for o, n in moved.items() if not (ROOT / n).exists() or (ROOT / n).read_bytes() != z.read(old[o])]
        checks['moved_files_byte_identical'] = not badm
    expect = (set(old) - removed - set(moved)) | set(moved.values()) | changed | set(rel['new'])
    cur = tree(ROOT)
    report_name = f"outputs/update_validation_{date.today():%Y%m%d}_v{version.replace('.', '')}.json"
    cur_cmp = cur | {report_name}
    checks['file_set_exact'] = cur_cmp == expect
    ok, n, tail = run_tests()
    checks['unit_tests_pass'] = ok and n >= rel['min_tests']
    regen = regenerate(rel)
    checks['all_outputs_reproduced'] = all(r['outputs_identical'] for r in regen)
    report = {'version': version, 'parent_version': rel['parent_version'], 'parent_sha256': rel['parent_sha256'],
              'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
              'unit_tests_total': n, 'regeneration': regen, 'moved_files': len(moved),
              'diagnostics': {'changed_unexpectedly': bad, 'moved_mismatch': badm,
                              'unexpected_files': sorted(cur_cmp - expect), 'missing_files': sorted(expect - cur_cmp),
                              'test_failure_tail': tail}}
    (ROOT / report_name).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def package(version, out):
    rel = registry()[version]
    files = sorted(tree(ROOT))
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(ROOT / f, 'election23/' + f)
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        for f in files:
            assert z.read('election23/' + f) == (ROOT / f).read_bytes(), f
    return {'file': str(Path(out).resolve()), 'bytes': Path(out).stat().st_size, 'sha256': sha(Path(out).read_bytes()),
            'files': len(files), 'parent_sha256': rel['parent_sha256']}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--release')
    ap.add_argument('--prior')
    ap.add_argument('--package')
    ap.add_argument('--legacy', choices=['validate', 'package'])
    ap.add_argument('rest', nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if a.list:
        for v, r in registry().items():
            kind = 'generic' if 'parent_sha256' in r else ('legacy' if (LEGACY / f"validate_release_{v.replace('.', '_')}.py").exists() else 'record')
            print(v, kind, r.get('drive_file_id', ''))
        print('archived legacy scripts:', len(list(LEGACY.glob('*.py'))))
        return 0
    if a.legacy:
        run_legacy(a.release, a.legacy, [x for x in a.rest if x != '--'])
        return 0
    if not a.release or not a.prior:
        ap.error('--release and --prior required')
    rep = validate(a.release, a.prior)
    print(json.dumps({'status': rep['status'], 'checks': rep['checks'], 'tests': rep['unit_tests_total'],
                      'diagnostics': {k: v for k, v in rep['diagnostics'].items() if v}}, ensure_ascii=False, indent=1))
    if rep['status'] != 'PASS':
        return 1
    if a.package:
        print(json.dumps(package(a.release, a.package), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
