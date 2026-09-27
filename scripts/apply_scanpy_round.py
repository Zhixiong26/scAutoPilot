#!/usr/bin/env python3
"""Materialize one frozen Scanpy MVP round into analysis.yaml without executing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class ApplyError(RuntimeError):
    pass


def load(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApplyError("cannot read %s: %s" % (path, exc))
    if not isinstance(value, dict):
        raise ApplyError("expected JSON object: %s" % path)
    return value


def digest(plan: Dict[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("plan_digest", None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, value: Dict[str, Any]) -> None:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp.%d" % os.getpid())
    temporary.write_bytes(encoded)
    temporary.replace(path)


def apply(project: Path, session_id: str, round_id: str, next_run_id: str) -> Dict[str, Any]:
    project = project.resolve()
    round_root = project / ".workflow" / "optimization" / session_id / round_id
    plan_path = round_root / "round_plan.json"
    plan = load(plan_path)
    if plan.get("plan_digest") != digest(plan):
        raise ApplyError("round plan digest does not match its contents")
    if not plan.get("frozen") or plan.get("status") != "next_candidate":
        raise ApplyError("round is not a frozen next_candidate plan")
    applied_path = round_root / "applied.json"
    if applied_path.exists():
        raise ApplyError("round was already applied: %s" % applied_path)
    diff = plan.get("parameter_diff") or {}
    if diff.get("parameter") not in {"n_pcs", "n_neighbors", "resolution", "min_dist"}:
        raise ApplyError("round does not contain one legal MVP parameter change")

    analysis_path = project / "config" / "analysis.yaml"
    document = load(analysis_path)
    scanpy = (document.get("analysis") or {}).get("scanpy")
    if not isinstance(scanpy, dict):
        raise ApplyError("analysis.yaml lacks analysis.scanpy")
    current = plan["current_parameters"]
    observed = {
        "n_pcs": scanpy["neighbors"]["n_pcs"],
        "n_neighbors": scanpy["neighbors"]["n_neighbors"],
        "resolution": scanpy["leiden"]["resolution"],
        "min_dist": scanpy["umap"]["min_dist"],
    }
    if observed != current:
        raise ApplyError("analysis.yaml has drifted from the frozen round's current parameters")
    before = json.loads(json.dumps(document))
    new_value = diff["new_value"]
    if diff["parameter"] == "n_pcs":
        scanpy["pca"]["n_comps"] = new_value
        scanpy["neighbors"]["n_pcs"] = new_value
    elif diff["parameter"] == "n_neighbors":
        scanpy["neighbors"]["n_neighbors"] = new_value
    elif diff["parameter"] == "resolution":
        scanpy["leiden"]["resolution"] = new_value
    else:
        scanpy["umap"]["min_dist"] = new_value
    notebook = scanpy.setdefault("notebook", {})
    notebook.update({"run_kind": "candidate", "iteration_id": next_run_id,
                     "analysis_confirmed": False, "overwrite_data_outputs": False})
    record = {"schema_version": 1, "applied_at": datetime.now(timezone.utc).isoformat(),
              "plan": str(plan_path), "plan_digest": plan["plan_digest"],
              "next_run_id": next_run_id, "parameter_diff": diff,
              "analysis_before_sha256": hashlib.sha256(
                  (json.dumps(before, sort_keys=True, separators=(",", ":"))).encode("utf-8")).hexdigest()}
    # Save auditable before/after snapshots beside the immutable decision, then
    # publish the project config and the applied marker atomically.
    atomic_json(round_root / "analysis_before.json", before)
    atomic_json(round_root / "analysis_after.json", document)
    atomic_json(analysis_path, document)
    atomic_json(applied_path, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--next-run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(apply(args.project, args.session_id, args.round_id, args.next_run_id),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApplyError, KeyError, OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
