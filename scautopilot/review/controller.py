"""Evidence-first Scanpy MVP reviewer and deterministic one-axis controller."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from scautopilot.policy.capabilities import CapabilityPolicy
from scautopilot.provenance.registry import ParameterRegistry

from .backend import (
    BackendError, DIRECTIONS, PARAMETERS, QUALITY, command_backend, rule_fallback,
    system_one_adapter_backend,
)
from .primitives import Choice, Noul, Score


class ReviewError(RuntimeError):
    pass


PARAMETER_IDS = {
    # One logical axis updates both the PCA capacity and the number of PCs used
    # by neighbors.  This makes the requested value 60 executable while still
    # changing one scientific parameter per round.
    "n_pcs": ("scanpy.pca.n_comps", "scanpy.neighbors.n_pcs"),
    "n_neighbors": ("scanpy.neighbors.n_neighbors",),
    "resolution": ("scanpy.leiden.resolution",),
    "min_dist": ("scanpy.umap.min_dist",),
}

QUESTIONS = {
    "accept": "Does the current result satisfy the predefined quality criteria?",
    "parameter": "Which single parameter should be adjusted next?",
    "direction": "In which direction should the selected parameter move?",
    "quality": "What is the overall current result quality on the ordered five-level scale?",
    "escalate": "Does the evidence require review by a stronger reasoning model or a human?",
}


def _load(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError("cannot read %s: %s" % (path, exc))
    if not isinstance(value, dict):
        raise ReviewError("expected a mapping in %s" % path)
    return value


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise ReviewError("immutable optimization artifact already exists: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp.%d" % os.getpid())
    temporary.write_bytes(encoded)
    temporary.replace(path)


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _find_candidate(project: Path, run_id: str, parameters: Mapping[str, Any]) -> Path:
    scanpy = project / "Results" / "runs" / run_id / "scanpy"
    iteration = str(parameters.get("iteration_id") or run_id)
    expected = scanpy / "iterations" / iteration / "candidate_analysis.h5ad"
    if expected.is_file():
        return expected
    matches = list(scanpy.glob("iterations/*/candidate_analysis.h5ad"))
    if len(matches) != 1:
        raise ReviewError("cannot uniquely locate candidate_analysis.h5ad for run %s" % run_id)
    return matches[0]


def _current_parameters(sidecar: Mapping[str, Any]) -> Dict[str, Any]:
    values = {
        "n_pcs": sidecar.get("n_pcs"),
        "n_neighbors": sidecar.get("n_neighbors"),
        "resolution": sidecar.get("leiden_resolution"),
        "min_dist": sidecar.get("umap_min_dist"),
    }
    if any(value is None for value in values.values()):
        raise ReviewError("Scanpy parameter sidecar lacks one of the four MVP parameters")
    return values


def _metric_vector(state: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    return {
        "trustworthiness": state["embedding"].get("trustworthiness"),
        "knn_preservation": state["embedding"].get("knn_preservation"),
        "silhouette": state["clustering"].get("silhouette"),
        "davies_bouldin": state["clustering"].get("davies_bouldin"),
        "celltype_asw": state["biology"].get("celltype_asw"),
        "ilisi": state["batch"].get("ilisi"),
        "batch_asw": state["batch"].get("batch_asw"),
    }


def _previous(session_root: Path, current: Mapping[str, Any], epsilon: float) -> Tuple[Optional[Dict[str, Any]], int]:
    rounds = sorted(path for path in session_root.glob("round_*") if path.is_dir())
    if not rounds:
        return None, 0
    prior_state = _load(rounds[-1] / "state.json")
    prior_plan = _load(rounds[-1] / "round_plan.json")
    expected = prior_plan.get("next_parameters")
    if prior_plan.get("status") == "next_candidate" and expected != current.get("parameters"):
        raise ReviewError("run parameters do not match the preceding frozen round plan")
    before, after = _metric_vector(prior_state), _metric_vector(current)
    delta = {key: (None if before[key] is None or after[key] is None else after[key] - before[key])
             for key in before}
    diff = prior_plan.get("parameter_diff") or {}
    previous = {
        "parent_round": rounds[-1].name,
        "parent_run_id": prior_state.get("run_id"),
        "parameter_changed": diff.get("parameter"),
        "old_value": diff.get("old_value"),
        "new_value": diff.get("new_value"),
        "metric_delta": delta,
    }
    # Direction-aware evidence only for the no-improvement safety stop; it is
    # not an optimization score and never merges the two reviewers.
    improvements = [delta[key] for key in ("trustworthiness", "knn_preservation", "silhouette",
                                            "celltype_asw", "ilisi") if delta[key] is not None]
    if delta["davies_bouldin"] is not None:
        improvements.append(-delta["davies_bouldin"])
    improved = any(value > epsilon for value in improvements)
    prior_decision = _load(rounds[-1] / "decision.json")
    prior_streak = int(prior_decision.get("no_improvement_streak", 0))
    return previous, 0 if improved else prior_streak + 1


def _questions(state_path: Path) -> Dict[str, Any]:
    evidence = [str(state_path)]
    return {
        "schema_version": 1,
        "judgments": [
            {"id": "accept", "primitive": "Noul", "instructions": QUESTIONS["accept"], "evidence": evidence},
            {"id": "parameter", "primitive": "Choice", "instructions": QUESTIONS["parameter"],
             "criteria": {"n_pcs": "change PCs used by the neighbor graph",
                          "n_neighbors": "change graph neighborhood size",
                          "resolution": "change Leiden granularity",
                          "min_dist": "change UMAP packing only",
                          "none": "no adjustment is needed",
                          "escalate": "the evidence is ambiguous"}, "evidence": evidence},
            {"id": "direction", "primitive": "Choice", "instructions": QUESTIONS["direction"],
             "criteria": {"increase": "move one grid step up", "decrease": "move one grid step down",
                          "keep": "do not change the selected value"}, "evidence": evidence},
            {"id": "quality", "primitive": "Score", "instructions": QUESTIONS["quality"],
             "levels": list(QUALITY), "evidence": evidence},
            {"id": "escalate", "primitive": "Noul", "instructions": QUESTIONS["escalate"], "evidence": evidence},
        ],
        "reviewers": {
            "clustering": {"parameters": ["n_pcs", "n_neighbors", "resolution"],
                           "metrics": ["silhouette", "davies_bouldin", "celltype_asw", "ilisi", "batch_asw"]},
            "umap": {"parameters": ["n_pcs", "n_neighbors", "min_dist"],
                     "metrics": ["trustworthiness", "knn_preservation"]},
        },
        "state": dict(state_path=str(state_path)),
    }


def _typed_judgments(raw: Mapping[str, Any], state_path: Path) -> Dict[str, Any]:
    backend, evidence = str(raw["backend"]), [str(state_path)]
    return {
        "schema_version": 1,
        "backend": backend,
        "accept": Noul("accept", QUESTIONS["accept"], raw["accept_probability"], backend, evidence).to_dict(),
        "parameter": Choice("parameter", QUESTIONS["parameter"],
                            {key: key for key in PARAMETERS}, raw["parameter"], backend, evidence).to_dict(),
        "direction": Choice("direction", QUESTIONS["direction"],
                            {key: key for key in DIRECTIONS}, raw["direction"], backend, evidence).to_dict(),
        "quality": Score("quality", QUESTIONS["quality"], list(QUALITY), raw["quality"], backend, evidence).to_dict(),
        "escalate": Noul("escalate", QUESTIONS["escalate"], raw["escalate_probability"], backend, evidence).to_dict(),
    }


def _step(grid: list, current: Any, direction: str) -> Optional[Any]:
    try:
        index = next(index for index, value in enumerate(grid) if abs(float(value) - float(current)) < 1e-9)
    except StopIteration:
        raise ReviewError("current parameter value %r is outside its frozen grid" % current)
    target = index + (1 if direction == "increase" else -1)
    return grid[target] if 0 <= target < len(grid) else None


def review_scanpy_run(project: Path, run_id: str, session_id: str) -> Dict[str, Any]:
    project = Path(project).resolve()
    summary_path = project / ".workflow" / "runs" / run_id / "run_summary.json"
    summary = _load(summary_path)
    if summary.get("status") != "complete":
        raise ReviewError("run is not complete: %s" % run_id)
    scanpy_tasks = [task for task in summary.get("tasks", []) if task.get("task") == "scanpy"]
    if len(scanpy_tasks) != 1 or not scanpy_tasks[0].get("evidence_valid"):
        raise ReviewError("run lacks one completed, evidence-valid Scanpy task")

    config = _load(project / "config" / "optimization.yaml")
    mvp = config.get("scanpy_mvp") or {}
    grids = mvp.get("parameter_grids") or {}
    if set(grids) != set(PARAMETER_IDS):
        raise ReviewError("optimization parameter grids must contain exactly the four MVP parameters")
    registry = ParameterRegistry.load(project / "config" / "parameters.yaml")
    policy_path = project / "tools" / "scautopilot" / "policy" / "capabilities.json"
    policy = CapabilityPolicy.load(policy_path) if policy_path.is_file() else CapabilityPolicy.load_default()
    registry_ids = [item for group in PARAMETER_IDS.values() for item in group]
    policy.effective_search_space(registry, registry_ids)

    sidecar_path = project / "Results" / "runs" / run_id / "scanpy" / "scanpy_parameters.json"
    sidecar = _load(sidecar_path)
    parameters = _current_parameters(sidecar)
    candidate = _find_candidate(project, run_id, sidecar)
    from .benchmark import calculate_scanpy_benchmarks
    benchmark = calculate_scanpy_benchmarks(candidate, parameters,
                                             int((mvp.get("benchmark") or {}).get("max_cells", 20000)))
    if max(grids["n_pcs"]) >= min(benchmark["dataset"]["n_cells"], benchmark["dataset"]["n_genes"]):
        raise ReviewError("n_pcs grid is not executable for this dataset's cell/feature dimensions")
    state = {"schema_version": 1, "run_id": run_id, "parameters": parameters,
             "dataset": benchmark["dataset"], "embedding": benchmark["embedding"],
             "clustering": benchmark["clustering"], "biology": benchmark["biology"],
             "batch": benchmark["batch"], "benchmark": benchmark["evaluation"],
             "evidence": {"run_summary": str(summary_path), "parameters": str(sidecar_path),
                          "candidate_h5ad": str(candidate)}}

    session_root = project / ".workflow" / "optimization" / session_id
    stopping = mvp.get("stopping") or {}
    previous, no_improvement = _previous(session_root, state, float(stopping.get("metric_epsilon", 0.001)))
    state["previous"] = previous
    round_index = len([path for path in session_root.glob("round_*") if path.is_dir()])
    round_root = session_root / ("round_%03d" % round_index)
    state_path = round_root / "state.json"
    questions_path = round_root / "questions.json"
    request = _questions(state_path)
    request["state_payload"] = state

    decision_backend = mvp.get("decision_backend") or {}
    legacy_jev = mvp.get("jev") or {}
    threshold_policy = mvp.get("policy") or legacy_jev
    mode = str(decision_backend.get("mode") or ("command" if legacy_jev.get("command") else "rule_fallback"))
    fallback_on_error = bool(decision_backend.get("fallback_on_error",
                                                  legacy_jev.get("fallback_on_error", True)))
    timeout = float(decision_backend.get("timeout_seconds", legacy_jev.get("timeout_seconds", 180)))
    backend_error = None
    backend_audit = {"requested_backend": mode}
    try:
        if mode in {"system_one_local", "system_one_commercial"}:
            settings = decision_backend.get(mode) or {}
            raw = system_one_adapter_backend(project, mode, settings, request, timeout)
            backend_audit.update(raw.pop("audit", {}))
        elif mode == "command":
            command = decision_backend.get("command") or legacy_jev.get("command")
            raw = command_backend(command, request, timeout)
        elif mode == "rule_fallback":
            raise BackendError("rule_fallback was explicitly selected")
        elif mode == "typesafe_jev":
            raise BackendError("typesafe_jev backend is reserved but not configured in V0.1")
        else:
            raise BackendError("unknown decision backend mode: %s" % mode)
    except BackendError as exc:
        if not fallback_on_error:
            raise ReviewError(str(exc))
        backend_error = str(exc)
        raw = rule_fallback(state)
        backend_audit.update({"effective_backend": raw["backend"], "degraded_reason": backend_error})
    backend_audit.setdefault("effective_backend", raw["backend"])
    judgments = _typed_judgments(raw, state_path)
    judgments["degraded_reason"] = backend_error
    judgments["backend_audit"] = str(round_root / "backend_audit.json")

    parameter = judgments["parameter"]["selected"]
    direction = judgments["direction"]["selected"]
    accept = float(judgments["accept"]["probability_yes"])
    escalate = float(judgments["escalate"]["probability_yes"])
    max_iterations = int(stopping.get("max_iterations", 20))
    max_no_improvement = int(stopping.get("max_no_improvement", 5))
    reason = None
    if round_index + 1 >= max_iterations:
        reason = "max_iterations"
    elif no_improvement >= max_no_improvement:
        reason = "max_no_improvement"
    elif accept >= float(threshold_policy.get("accept_threshold", 0.8)):
        reason = "accepted"
    elif escalate >= float(threshold_policy.get("escalate_threshold", 0.8)) or parameter == "escalate":
        reason = "escalate"
    elif parameter == "none" or direction == "keep":
        reason = "no_change"

    next_parameters = dict(parameters)
    diff = None
    if reason is None:
        value = _step(list(grids[parameter]), parameters[parameter], direction)
        if value is None:
            reason = "parameter_bound"
        else:
            next_parameters[parameter] = value
            diff = {"parameter": parameter, "parameter_ids": list(PARAMETER_IDS[parameter]),
                    "direction": direction, "old_value": parameters[parameter], "new_value": value}
    status = "next_candidate" if diff else "stopped" if reason in {"accepted", "max_iterations", "max_no_improvement", "no_change"} else "review_required"
    decision = {"schema_version": 1, "status": status, "reason": reason,
                "no_improvement_streak": no_improvement, "selected_parameter": parameter,
                "selected_direction": direction, "accept_probability": accept,
                "escalate_probability": escalate, "backend": judgments["backend"]}
    plan = {"schema_version": 1, "frozen": True, "session_id": session_id,
            "round_id": round_root.name, "parent_run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(), "status": status,
            "current_parameters": parameters, "next_parameters": next_parameters,
            "parameter_diff": diff, "decision": decision,
            "fixed": mvp.get("fixed") or {}}
    plan["plan_digest"] = _digest(plan)
    # Publish a round only after every calculation and policy check succeeds.
    # A backend/schema failure therefore cannot strand a half-written immutable
    # round that changes recovery semantics.
    _write_immutable(state_path, state)
    _write_immutable(questions_path, request)
    _write_immutable(round_root / "backend_audit.json", backend_audit)
    _write_immutable(round_root / "judgments.json", judgments)
    _write_immutable(round_root / "decision.json", decision)
    _write_immutable(round_root / "round_plan.json", plan)
    return {"session_id": session_id, "round_id": round_root.name, "status": status,
            "reason": reason, "backend": judgments["backend"], "degraded_reason": backend_error,
            "parameter_diff": diff, "round_plan": str(round_root / "round_plan.json")}
