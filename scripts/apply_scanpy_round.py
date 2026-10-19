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
from optimization_state import exclusive_lock, identifier, mapping, digest as config_digest
from _common import sha256_file


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
    for name, value in [('session-id', session_id), ('round-id', round_id), ('next-run-id', next_run_id)]:
        identifier(value, name)
    with exclusive_lock(project / '.workflow/optimization/.apply.lock'):
        with exclusive_lock(project / '.workflow/optimization' / session_id / '.lock'):
            return _apply(project, session_id, round_id, next_run_id)


def _apply(project: Path, session_id: str, round_id: str, next_run_id: str) -> Dict[str, Any]:
    round_root = project / ".workflow" / "optimization" / session_id / round_id
    plan_path = round_root / "round_plan.json"
    plan = load(plan_path)
    if plan.get("plan_digest") != digest(plan):
        raise ApplyError("round plan digest does not match its contents")
    if not plan.get("frozen") or plan.get("status") != "next_candidate":
        raise ApplyError("round is not a frozen next_candidate plan")
    if plan.get('schema_version') not in {2, 3} or not plan.get('analysis_config_digest'):
        raise ApplyError('legacy round lacks a complete config binding; review in a new session')
    if plan.get('session_id') != session_id or plan.get('round_id') != round_id:
        raise ApplyError('round identity differs from its location')
    applied_path = round_root / "applied.json"
    if applied_path.exists():
        raise ApplyError("round was already applied: %s" % applied_path)
    diff = plan.get("parameter_diff") or {}
    if diff.get("parameter") not in {"n_pcs", "n_neighbors", "resolution", "min_dist"}:
        raise ApplyError("round does not contain one legal MVP parameter change")
    current = plan['current_parameters']
    base = plan.get('base_parameters', current) if plan['schema_version'] == 3 else current
    if plan['schema_version'] == 3:
        base_path = Path(plan.get('base_state_path', '')).resolve()
        session_root = round_root.parent.resolve()
        if base_path.parent.parent != session_root or base_path.name != 'state.json':
            raise ApplyError('base state must belong to this optimization session')
        base_state = load(base_path)
        if (config_digest(base_state) != plan.get('base_state_digest') or
                base_state.get('parameters') != base or base_state.get('run_id') != plan.get('base_run_id') or
                base_state.get('pca_n_comps') != plan.get('base_pca_n_comps')):
            raise ApplyError('incumbent base state differs from frozen plan')
        current_state = load(round_root / 'state.json')
        if (config_digest(current_state) != plan.get('review_state_digest') or
                base_state.get('fixed_science') != current_state.get('fixed_science') or
                base_state.get('code_signature') != current_state.get('code_signature') or
                base_state.get('benchmark') != current_state.get('benchmark')):
            raise ApplyError('incumbent restoration would change fixed science or evaluation')
    expected = dict(base)
    expected[diff['parameter']] = diff.get('new_value')
    if (set(current) != {'n_pcs', 'n_neighbors', 'resolution', 'min_dist'} or
            set(base) != set(current) or diff.get('old_value') != base[diff['parameter']] or
            expected != plan.get('next_parameters') or expected == base):
        raise ApplyError('round diff and next_parameters disagree or change more than one axis')
    if next_run_id == plan.get('parent_run_id') or (project / '.workflow/runs' / next_run_id).exists() or (
            project / 'Results/runs' / next_run_id).exists():
        raise ApplyError('next-run-id must identify a new run')

    analysis_path = project / "config" / "analysis.yaml"
    document = mapping(analysis_path)
    optimization = mapping(project / 'config/optimization.yaml')
    if config_digest(optimization) != plan.get('optimization_config_digest'):
        raise ApplyError('optimization policy drifted from the frozen round')
    grid = optimization['scanpy_mvp']['parameter_grids'][diff['parameter']]
    try:
        old_index, new_index = grid.index(diff['old_value']), grid.index(diff['new_value'])
    except ValueError as exc:
        raise ApplyError('round change is outside the frozen grid') from exc
    if abs(new_index - old_index) != 1:
        raise ApplyError('round must move one adjacent grid step')
    for path, expected_sha in (plan.get('source_sha256') or {}).items():
        if Path(path) != analysis_path and sha256_file(Path(path)) != expected_sha:
            raise ApplyError('source evidence changed: %s' % path)

    pending_path = round_root / 'apply_pending.json'
    if pending_path.exists():
        pending = load(pending_path)
        if pending.get('next_run_id') != next_run_id or pending.get('plan_digest') != plan['plan_digest']:
            raise ApplyError('incomplete application belongs to another run/plan')
        before = load(round_root / 'analysis_before.json')
        after = load(round_root / 'analysis_after.json')
        if (config_digest(before) != pending['analysis_before_sha256'] or
                config_digest(after) != pending['analysis_after_sha256']):
            raise ApplyError('application recovery snapshots were modified')
        if config_digest(document) not in {config_digest(before), config_digest(after)}:
            raise ApplyError('config drifted during interrupted application')
        atomic_json(analysis_path, after)
        atomic_json(applied_path, pending)
        return pending
    if config_digest(document) != plan['analysis_config_digest']:
        raise ApplyError('analysis.yaml has drifted from the complete frozen configuration')
    scanpy = (document.get("analysis") or {}).get("scanpy")
    if not isinstance(scanpy, dict):
        raise ApplyError("analysis.yaml lacks analysis.scanpy")
    observed = {
        "n_pcs": scanpy["neighbors"]["n_pcs"],
        "n_neighbors": scanpy["neighbors"]["n_neighbors"],
        "resolution": scanpy["leiden"]["resolution"],
        "min_dist": scanpy["umap"]["min_dist"],
    }
    if observed != current:
        raise ApplyError("analysis.yaml has drifted from the frozen round's current parameters")
    before = json.loads(json.dumps(document))
    if plan['schema_version'] == 3:
        # Explicit restoration is not another scientific perturbation. The
        # candidate changes one adjacent axis relative to this frozen base.
        scanpy['pca']['n_comps'] = plan['base_pca_n_comps']
        scanpy['neighbors']['n_pcs'] = base['n_pcs']
        scanpy['neighbors']['n_neighbors'] = base['n_neighbors']
        scanpy['leiden']['resolution'] = base['resolution']
        scanpy['umap']['min_dist'] = base['min_dist']
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
              "base_run_id": plan.get('base_run_id', plan.get('parent_run_id')),
              "restore_incumbent": plan.get('restore_incumbent', False),
              "analysis_before_sha256": config_digest(before),
              "analysis_after_sha256": config_digest(document)}
    # Save auditable before/after snapshots beside the immutable decision, then
    # publish the project config and the applied marker atomically.
    atomic_json(round_root / "analysis_before.json", before)
    atomic_json(round_root / "analysis_after.json", document)
    atomic_json(pending_path, record)
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
