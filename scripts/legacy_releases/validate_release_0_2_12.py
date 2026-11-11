#!/usr/bin/env python3
"""Validate a synthetic-only joint vote conservation release without changing live inputs."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIOR_SHA = "152df09865c99a2c30bec0d9a0879fa8318f4bd5108b64b26fe4d2c6184367ce"

def read_json(name):
    return json.loads((ROOT / name).read_text())

def main():
    prior_path = Path(sys.argv[1])
    assert hashlib.sha256(prior_path.read_bytes()).hexdigest() == PRIOR_SHA
    with zipfile.ZipFile(prior_path) as prior:
        assert prior.testzip() is None
        assert json.loads(prior.read("election23/state.json"))["version"] == "0.2.11"
        protected = [n.removeprefix("election23/") for n in prior.namelist()
                     if not n.endswith("/") and (n.startswith("election23/data/") or n.startswith("election23/config/"))]
        protected += ["model.py", "outputs/model_report.json", "outputs/model_report_monthly.json",
                      "scripts/partial_identification.py", "outputs/optional_remainder_diagnostic_253.json",
                      "scripts/validate_historical_frames.py", "outputs/historical_frame_inventory.json",
                      "scripts/build_backtest_readiness.py", "outputs/backtest_readiness.json"]
        for name in protected:
            assert (ROOT / name).read_bytes() == prior.read("election23/" + name), name
    checks = {"all_existing_data_config_engine_scenarios_and_historical_diagnostics_immutable": True}
    tests = ["test_model.py", "test_safety_guards.py", "test_boundary_inventory.py",
             "test_ward_inventory.py", "test_historical_frame_archive.py", "test_historical_inventory.py",
             "test_partial_identification.py", "test_historical_roles.py", "test_backtest_readiness.py",
             "test_historical_580.py", "test_historical_579.py", "test_joint_vote_conservation.py"]
    for args, count in [(tests, 151), (["discover", "-s", "data/history_2020", "-p", "test_crosscheck.py"], 8)]:
        result = subprocess.run([sys.executable, "-m", "unittest", *args], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0 and f"Ran {count} tests" in result.stderr, result.stdout + result.stderr
    checks["all_159_tests_pass"] = True
    sys.path.insert(0, str(ROOT))
    from model import read_baseline, build_report
    districts = read_baseline(ROOT / "data/baseline_2024.csv")
    polls = read_json("data/polls.json")
    config = read_json("config/frame_comparison.json")
    assert len(districts) == 254 and sum(len(d["candidates"]) for d in districts) == 693
    assert all(not d["errors"] for d in districts)
    for district in districts:
        assert sum(c["votes"] for c in district["candidates"]) == district["candidates"][0]["valid_votes"]
    reference = build_report(districts, polls, config, draws=100, seed=20261016)
    assert reference == build_report(districts, polls, config, draws=100, seed=20261016)
    mutated = copy.deepcopy(polls)
    count = 0
    for row in mutated["polls"]:
        if row.get("question_type") == "party_support":
            row.clear()
            row.update(question_type="party_support", shares={"malformed": -99999})
            count += 1
    assert count == 19
    assert reference == build_report(districts, mutated, config, draws=100, seed=20261016)
    removed = copy.deepcopy(polls)
    removed["polls"] = [r for r in removed["polls"] if r.get("question_type") != "party_support"]
    assert reference == build_report(districts, removed, config, draws=100, seed=20261016)
    checks["actual_100draw_party_input_mutation_deletion_seed_invariance"] = True
    for report in [reference, read_json("outputs/model_report.json"), read_json("outputs/model_report_monthly.json")]:
        assert report["coverage"]["complete"] and report["coverage"]["observed_districts"] == 254
        for scenario in report["scenarios"]:
            assert len(scenario["districts"]) == 254 and all(scenario["checks"].values())
            assert scenario["simulated_districts"] == 245 and scenario["not_estimable_districts"] == 9
            assert abs(sum(v["mean_seats"] for v in scenario["national_district_seats"].values()) - 245) < .01
    checks["254_district_693_candidate_vote_and_245_plus_9_seat_accounting"] = True
    from scripts.build_backtest_readiness import readiness_report
    ready = readiness_report()
    assert ready == read_json("outputs/backtest_readiness.json")
    assert ready["fold_count"] == 5 and ready["executable_fold_count"] == 0
    assert not ready["backtest_executed"] and ready["performance_metrics"] is None
    checks["five_readiness_manifests_blocked_without_backtest_or_scores"] = True
    inventory = read_json("outputs/historical_frame_inventory.json")
    assert inventory["wave_count"] == 6 and inventory["observation_count"] == 54
    assert not any(inventory[k] for k in ("party_support_used", "training_approved", "current_model_linked",
        "geography_approved", "cross_election_pooling_approved", "party_successor_mapping_created", "wave_pooling_or_weights_created"))
    diagnostic = read_json("outputs/optional_remainder_diagnostic_253.json")
    assert diagnostic["status"] == "PASS" and diagnostic["diagnostic_district_count"] == 253
    assert diagnostic["remainder_cap_valid_votes"] == 2800361
    assert not any(diagnostic[k] for k in ("training_approved", "current_model_linked", "allocation_weights_created", "unknown_geography_solved"))
    assert diagnostic["geographic_crosswalk_eligible_districts"] == 0
    checks["historical_6_waves_54_rows_and_253_optional_box_diagnostics_unchanged"] = True
    synthetic = read_json("outputs/joint_vote_conservation_synthetic.json")
    from scripts.validate_joint_vote_conservation import build_report as build_joint_report
    assert synthetic == build_joint_report()
    assert synthetic["status"] == "ARITHMETIC_PASS_SYNTHETIC_ONLY"
    assert synthetic["synthetic_only"] is True and synthetic["arithmetic_pass"] is True
    for key in ("actual_election_data_loaded", "geography_approved", "training_approved", "current_model_linked",
                "actual_geographic_edges_verified", "fixed_named_ward_geography_verified", "allocation_generated",
                "backtest_executed", "win_probabilities_produced", "party_support_used"):
        assert synthetic[key] is False, key
    for key in ("real_allocations_checked", "historical_backtests_executed", "geographic_crosswalk_eligible_districts"):
        assert synthetic[key] == 0, key
    assert synthetic["synthetic_case_count"] == 3 and synthetic["valid_case_count"] == 1
    assert synthetic["invalid_cases_rejected"] == 2
    checks["new_joint_conservation_is_synthetic_only_not_real_vote_allocation"] = True
    text = (ROOT / "outputs/DISTRICT_STATUS.md").read_text()
    assert text.count("정부지원·견제 연동(조건부·미보정)") == 245
    assert text.count("보류: 양당 후보 구도 확인 필요") == 9
    state = read_json("state.json")
    assert state["version"] == "0.2.12" and state["engine_version"] == "0.2.3"
    assert state["unit_test_count"] == 159
    assert state["historical_frame_wave_count"] == 6 and state["historical_frame_archive_observation_count"] == 54
    assert state["historical_backtests_executed"] == 0 and state["geographic_crosswalk_eligible_districts"] == 0
    assert state["party_support_input_allowed"] is False and state["scenario_numbers_changed"] is False
    for name, digest in state["input_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(prior_path) as prior:
        for name in protected:
            assert (ROOT / name).read_bytes() == prior.read("election23/" + name), name
    checks["protected_files_still_identical_after_tests"] = True
    result = {
        "project_version": "0.2.12", "engine_version": "0.2.3", "verified_date": "2026-10-19",
        "status": "PASS", "unit_tests_total": 159, "checks": checks,
        "historical_archive_wave_count": 6, "historical_archive_observations": 54,
        "historical_backtests_executed": 0, "geographic_crosswalk_eligible_districts": 0,
        "scenario_recalculated_for_release": False, "scenario_numbers_changed": False,
        "joint_conservation_synthetic_only": True, "real_geographic_allocation_created": False,
        "partial_identification_geography_policy_complete": False,
        "remaining_gates": ["verified_geographic_ward_crosswalk", "real_joint_geographic_remainder_constraints",
                            "historical_baseline_availability", "historical_candidate_party_mapping",
                            "method_comparability", "time_split_calibration"],
        "protected_sha256": {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in protected},
        "synthetic_report_sha256": hashlib.sha256((ROOT / "outputs/joint_vote_conservation_synthetic.json").read_bytes()).hexdigest()
    }
    (ROOT / "outputs/update_validation_20261019_1110.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "protected_sha256"}, ensure_ascii=False))

if __name__ == "__main__":
    main()

