#!/usr/bin/env python3
"""Build a whitelisted synthetic-only release from the verified prior archive."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

CHANGED = {"README.md", "CHANGELOG.md", "BACKLOG.md", "UPDATE_PROTOCOL.md", "model_notes.md",
           "state.json", "scripts/render_summary.py"}
NEW = {"scripts/validate_joint_vote_conservation.py", "test_joint_vote_conservation.py",
       "scripts/validate_release_0_2_12.py", "scripts/package_release_0_2_12.py",
       "outputs/research_check_20261019_1110.json"}
GENERATED = {"outputs/DISTRICT_STATUS.md", "outputs/update_validation_20261019_1110.json",
             "outputs/joint_vote_conservation_synthetic.json"}
PRIOR_SHA = "152df09865c99a2c30bec0d9a0879fa8318f4bd5108b64b26fe4d2c6184367ce"
SOURCE_SHA = "690176009970c6c45e37fee6a65af43c81635416915467a6177a369bd64ed74f"

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--working", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert args.output.resolve() != args.prior.resolve(), "Never overwrite canonical input"
    assert hashlib.sha256(args.prior.read_bytes()).hexdigest() == PRIOR_SHA
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="verified0212_", dir=args.output.parent))
    with zipfile.ZipFile(args.prior) as prior:
        assert prior.testzip() is None
        names = prior.namelist()
        assert len(names) == len(set(names))
        assert all(n.startswith("election23/") and ".." not in Path(n).parts for n in names)
        assert json.loads(prior.read("election23/state.json"))["version"] == "0.2.11"
        prior.extractall(staging)
    project = staging / "election23"
    for relative in sorted(CHANGED | NEW):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.working / relative, target)
    for command in ([sys.executable, "scripts/validate_joint_vote_conservation.py", "--output", "outputs/joint_vote_conservation_synthetic.json"],
                    [sys.executable, "scripts/render_summary.py"],
                    [sys.executable, "scripts/validate_release_0_2_12.py", str(args.prior.resolve())]):
        subprocess.run(command, cwd=project, check=True)
    with zipfile.ZipFile(args.prior) as prior:
        old_files = {n for n in prior.namelist() if not n.endswith("/")}
        for name in old_files:
            relative = name.removeprefix("election23/")
            if relative not in CHANGED | GENERATED:
                assert (project / relative).read_bytes() == prior.read(name), name
    files = [p for p in sorted(project.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    final_names = {str(p.relative_to(staging)) for p in files}
    old_kept = {n for n in old_files if "__pycache__" not in Path(n).parts and not n.endswith(".pyc")}
    assert final_names == old_kept | {"election23/" + n for n in NEW | GENERATED}, final_names ^ old_kept
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files:
            archive.write(file, file.relative_to(staging))
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        assert hashlib.sha256(archive.read("election23/data/history_2020/nec_2020_original_tables.zip")).hexdigest() == SOURCE_SHA
        audit = json.loads(archive.read("election23/outputs/update_validation_20261019_1110.json"))
        assert audit["status"] == "PASS" and audit["unit_tests_total"] == 159
        assert json.loads(archive.read("election23/state.json"))["version"] == "0.2.12"
        for name, digest in audit["protected_sha256"].items():
            assert hashlib.sha256(archive.read("election23/" + name)).hexdigest() == digest, name
    print(json.dumps({"status": "PASS", "zip_path": str(args.output.resolve()),
                      "size_bytes": args.output.stat().st_size,
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "staging": str(project)}, ensure_ascii=False))

if __name__ == "__main__":
    main()

