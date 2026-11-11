"""Synthetic-only, joint conservation checks; never construct a crosswalk.

Separate candidate-wise bounds do not guarantee that several recipient districts
can be satisfied at once. This validator checks a *supplied* synthetic allocation
jointly, retaining each source district / original party / candidate identity and
keeping named-ward votes separate from unlocated votes. Arithmetic validity does
not certify an edge, ward boundary, candidate coalition, or geographic allocation.
No election files, party-support polls, model engine, or historical fits are read.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


IDENTITY = ("source_district", "party_original", "candidate")
VOTE_FIELDS = ("fixed_named_ward", "unlocated")
SOURCE_FIELDS = frozenset(IDENTITY + VOTE_FIELDS)
ALLOCATION_FIELDS = SOURCE_FIELDS | {"target_district"}
FALSE_FLAGS = (
    "actual_election_data_loaded", "actual_geographic_edges_verified",
    "fixed_named_ward_geography_verified", "geography_approved",
    "training_approved", "current_model_linked", "backtest_executed",
    "win_probabilities_produced", "allocation_generated", "party_support_used",
)


def _name(value, field):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be a nonempty, unpadded string")
    return value


def _row(row, fields):
    if not isinstance(row, dict) or set(row) != fields:
        raise ValueError("unexpected or missing row fields")
    for field in IDENTITY:
        _name(row[field], field)
    for field in VOTE_FIELDS:
        if type(row[field]) is not int or row[field] < 0:
            raise ValueError(f"{field} must be a nonnegative integer (not bool)")
    return tuple(row[field] for field in IDENTITY)


def validate_joint_conservation(sources, targets, allowed_edges, allocations,
                                *, synthetic_only=False):
    """Validate supplied synthetic rows; return audit data or raise ValueError.

    The explicit flag is a caller assertion, not a test of data provenance.
    Edges are supplied hypothetical permissions, never verified geography.
    Every source-candidate identity and every named target must be represented,
    including explicit zero rows when needed. Neither missing nor extra source
    identities may be silently collapsed into another candidate or district.
    """
    if synthetic_only is not True:
        raise ValueError("only explicitly synthetic inputs are permitted")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a nonempty list")
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a nonempty list")
    target_set = {_name(target, "target_district") for target in targets}
    if len(target_set) != len(targets):
        raise ValueError("duplicate target")
    ledger = {}
    for row in sources:
        key = _row(row, SOURCE_FIELDS)
        if key in ledger:
            raise ValueError("duplicate source-candidate identity")
        ledger[key] = {field: row[field] for field in VOTE_FIELDS}
    source_districts = {key[0] for key in ledger}
    if not isinstance(allowed_edges, list) or not allowed_edges:
        raise ValueError("allowed_edges must be a nonempty list")
    edge_set = set()
    for edge in allowed_edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise ValueError("edge must contain source and target districts")
        source, target = (_name(edge[0], "source_district"),
                          _name(edge[1], "target_district"))
        if source not in source_districts or target not in target_set:
            raise ValueError("unknown source or target in edge")
        if (source, target) in edge_set:
            raise ValueError("duplicate allowed edge")
        edge_set.add((source, target))
    if not isinstance(allocations, list) or not allocations:
        raise ValueError("allocations must be a nonempty list")
    received = {key: {field: 0 for field in VOTE_FIELDS} for key in ledger}
    target_totals = {target: {field: 0 for field in VOTE_FIELDS}
                     for target in targets}
    seen_rows, seen_sources, seen_targets = set(), set(), set()
    for row in allocations:
        key = _row(row, ALLOCATION_FIELDS)
        target = _name(row["target_district"], "target_district")
        if key not in ledger:
            raise ValueError("unknown source-candidate identity")
        if target not in target_set:
            raise ValueError("unknown target")
        if (key[0], target) not in edge_set:
            raise ValueError("allocation uses an unlisted synthetic edge")
        allocation_key = key + (target,)
        if allocation_key in seen_rows:
            raise ValueError("duplicate source-candidate-target row")
        seen_rows.add(allocation_key)
        seen_sources.add(key)
        seen_targets.add(target)
        for field in VOTE_FIELDS:
            received[key][field] += row[field]
            target_totals[target][field] += row[field]
    if seen_sources != set(ledger):
        raise ValueError("source-candidate identity lacks explicit representation")
    if seen_targets != target_set:
        raise ValueError("target lacks explicit representation")
    for key, expected in ledger.items():
        for field in VOTE_FIELDS:
            if received[key][field] != expected[field]:
                raise ValueError(f"joint conservation failed: {key!r} / {field}")
    totals = {field: sum(row[field] for row in ledger.values())
              for field in VOTE_FIELDS}
    return {
        "status": "ARITHMETIC_PASS_SYNTHETIC_ONLY",
        "arithmetic_pass": True,
        "synthetic_only": True,
        "source_candidate_count": len(ledger),
        "target_count": len(targets),
        "allocation_row_count": len(allocations),
        "source_totals": totals,
        "allocated_totals": {field: sum(row[field] for row in received.values())
                             for field in VOTE_FIELDS},
        "synthetic_target_totals": target_totals,
        "real_allocations_checked": 0,
        "geographic_crosswalk_eligible_districts": 0,
        "historical_backtests_executed": 0,
        **{flag: False for flag in FALSE_FLAGS},
        "limitation": "Joint arithmetic only; synthetic edges and named-ward "
                      "placements are not verified geography or model inputs.",
    }


def build_synthetic_report():
    """Three fixed synthetic fixtures: one valid split, two duplication errors."""
    source = {"source_district": "synthetic_source", "party_original": "synthetic_party",
              "candidate": "synthetic_candidate", "fixed_named_ward": 10, "unlocated": 4}
    targets = ["synthetic_A", "synthetic_B"]
    edges = [[source["source_district"], target] for target in targets]
    valid = [dict(source, target_district=targets[0], fixed_named_ward=6, unlocated=1),
             dict(source, target_district=targets[1], fixed_named_ward=4, unlocated=3)]
    cases = [("conserved_split", valid, True),
             ("duplicated_named_ward", [dict(row, fixed_named_ward=10) for row in valid], False),
             ("duplicated_unlocated", [dict(row, unlocated=4) for row in valid], False)]
    results = []
    valid_result = None
    for name, rows, expected in cases:
        try:
            result = validate_joint_conservation([source], targets, edges, rows, synthetic_only=True)
            accepted, reason = True, None
            valid_result = result
        except ValueError as exc:
            accepted, reason = False, str(exc)
        if accepted != expected:
            raise AssertionError(f"synthetic fixture produced unexpected result: {name}")
        results.append({"case": name, "expected_acceptance": expected,
                        "accepted": accepted, "rejection_reason": reason})
    return {**valid_result, "synthetic_case_count": 3, "valid_case_count": 1,
            "invalid_cases_rejected": 2, "cases": results,
            "scope": "Implementation diagnostic, not historical validation or a crosswalk."}


def build_report():
    return build_synthetic_report()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "outputs" /
                        "joint_vote_conservation_synthetic.json")
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "synthetic_case_count": 3, "valid_case_count": 1,
                      "invalid_cases_rejected": 2}, ensure_ascii=False))


if __name__ == "__main__":
    main()
