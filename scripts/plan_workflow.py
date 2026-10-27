#!/usr/bin/env python3
"""Build a route-aware task DAG without submitting jobs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import WorkflowError, git_commit, load_project, task_is_implemented, write_json, runtime_identity
from validate_project import validate
from result_paths import infer_category, require_unused_result, validate_output_commands, validate_run_id


def task(name: str, profile: str, dependencies: List[str] | None = None,
         parameters: Dict[str, Any] | None = None, environment: str = "orchestrator",
         outputs: List[str] | None = None, required_environments: List[str] | None = None) -> dict:
    if outputs is None:
        outputs = ["{task_dir}/task_outputs.json"]
    return {
        "id": name, "profile": profile, "dependencies": dependencies or [],
        "parameters": parameters or {}, "environment": environment,
        "required_environments": required_environments or [environment],
        "outputs": outputs or [],
    }


ROUTE_PREREQUISITES = {
    "methscan_dmr": {"methscan_vmr"},
    "methylvi_allcools": {"allcools"},
    "methylvi_vmr": {"methscan_vmr"},
    "methylvi_vmr_dmr": {"methscan_vmr", "methscan_dmr", "methylvi_vmr"},
}


def close_routes(routes: Dict[str, bool]) -> Dict[str, bool]:
    closed = dict(routes)
    changed = True
    while changed:
        changed = False
        for route, prerequisites in ROUTE_PREREQUISITES.items():
            if closed.get(route):
                for prerequisite in prerequisites:
                    if not closed.get(prerequisite):
                        closed[prerequisite] = True
                        changed = True
    return closed


def validate_dag(tasks: List[dict]) -> None:
    identifiers = [item["id"] for item in tasks]
    if len(identifiers) != len(set(identifiers)):
        raise WorkflowError("workflow DAG contains duplicate task IDs")
    by_id = {item["id"]: item for item in tasks}
    for item in tasks:
        missing = sorted(set(item["dependencies"]) - set(by_id))
        if missing:
            raise WorkflowError("task %s has unknown dependencies: %s" %
                                (item["id"], ", ".join(missing)))
    visiting, visited = set(), set()

    def visit(name: str) -> None:
        if name in visiting:
            raise WorkflowError("workflow DAG contains a dependency cycle at %s" % name)
        if name in visited:
            return
        visiting.add(name)
        for dependency in by_id[name]["dependencies"]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for identifier in identifiers:
        visit(identifier)


def make_tasks(routes: Dict[str, bool], analysis: Dict[str, Any]) -> List[dict]:
    routes = close_routes(routes)
    delivery = analysis.get("figures_comparison", {})
    if not isinstance(delivery, dict) or not isinstance(delivery.get("enabled", True), bool):
        raise WorkflowError("analysis.figures_comparison.enabled must be a boolean")
    thresholds = analysis.get("methscan", {}).get("vmr_thresholds", [0.01, 0.02, 0.05])
    feature_targets = analysis.get("methylvi", {}).get("feature_targets", [10000, 30000])
    if any(routes.get(name) for name in ("methscan_vmr", "methscan_dmr", "methylvi_vmr", "methylvi_vmr_dmr")):
        if not isinstance(thresholds, list) or not thresholds:
            raise WorkflowError("analysis.methscan.vmr_thresholds must be a non-empty list")
    if any(routes.get(name) for name in ("allcools", "methylvi_allcools", "methylvi_vmr", "methylvi_vmr_dmr")):
        if not isinstance(feature_targets, list) or not feature_targets:
            raise WorkflowError("analysis.methylvi.feature_targets must be a non-empty list")
    tasks: List[dict] = []
    if routes.get('methylation_iteration'):
        from scautopilot.review.methylation import validate_spec
        specs = analysis.get('methylation_iteration', [])
        if not isinstance(specs, list) or not specs:
            raise WorkflowError('analysis.methylation_iteration requires explicit source experiments')
        for spec in specs:
            spec = validate_spec(spec)
            tasks.append(task('methylation_iter_' + spec['id'], 'plot',
                parameters={'spec': spec}, environment='scanpy_allcools'))
    if routes.get("scanpy"):
        tasks.append(task("scanpy", "scanpy", environment="scanpy_allcools"))
    needs_filter = bool(routes.get("methscan_vmr") or routes.get("allcools"))
    methscan_tail = None
    if needs_filter:
        tasks.extend([
            task("methscan_select_convert", "io_builder", environment="methscan",
                 required_environments=["methscan", "scanpy_allcools"]),
            task("methscan_prepare", "serial", ["methscan_select_convert"], environment="methscan",
                 required_environments=["methscan", "scanpy_allcools"]),
            task("methscan_filter", "serial", ["methscan_prepare"], environment="methscan",
                 required_environments=["methscan", "scanpy_allcools"]),
        ])
    if routes.get("methscan_vmr"):
        tasks.append(task("methscan_smooth", "serial", ["methscan_filter"], environment="methscan",
                          required_environments=["methscan", "scanpy_allcools"]))
        methscan_tail = "methscan_smooth"
        for threshold in thresholds:
            tasks.append(task("methscan_vmr_%s" % threshold, "methscan_branch", [methscan_tail],
                              {"threshold": threshold}, "methscan",
                              required_environments=["methscan", "scanpy_allcools"]))
    if routes.get("methscan_dmr") and methscan_tail:
        tasks.append(task("methscan_pairwise_dmr", "dmr", [methscan_tail], environment="methscan",
                          required_environments=["methscan", "scanpy_allcools"]))
        tasks.append(task("methscan_hypo_heatmaps", "plot", ["methscan_pairwise_dmr"], environment="methscan",
                          required_environments=["methscan", "scanpy_allcools"]))
        tasks.append(task("methscan_pooled_dmr", "dmr", [methscan_tail], environment="methscan",
                          required_environments=["methscan", "scanpy_allcools"]))
    if routes.get("allcools"):
        tasks.append(task("allcools_features", "feature_builder", ["methscan_filter"],
                          environment="scanpy_allcools",
                          required_environments=["scanpy_allcools", "methylvi"]))
    if routes.get("methylvi_allcools"):
        for count in feature_targets:
            tasks.append(task("methylvi_allcools_%s" % count, "trainer", ["allcools_features"], {"features": count}, "methylvi"))
    if routes.get("methylvi_vmr") and methscan_tail:
        for threshold in thresholds:
            vmr_task = "methscan_vmr_%s" % threshold
            feature_task = "methylvi_vmr_features_%s" % threshold
            tasks.append(task(feature_task, "feature_builder", [vmr_task], {"threshold": threshold}, "methylvi"))
            for count in feature_targets:
                tasks.append(task("methylvi_vmr_%s_%s" % (threshold, count), "trainer", [feature_task], {"threshold": threshold, "features": count}, "methylvi"))
    if routes.get("methylvi_vmr_dmr") and methscan_tail:
        tasks.append(task("pooled_dmr_prepare", "dmr_prepare", ["methscan_pooled_dmr"], environment="methylvi"))
        first_threshold = thresholds[0]
        tasks.append(task("pooled_dmr_counts", "feature_builder", ["pooled_dmr_prepare", "methylvi_vmr_features_%s" % first_threshold], environment="methylvi"))
        for threshold in thresholds:
            for count in feature_targets:
                name = "methylvi_vmr_dmr_%s_%s" % (threshold, count)
                base_features = "methylvi_vmr_features_%s" % threshold
                tasks.append(task(name, "trainer", ["pooled_dmr_counts", base_features], {"threshold": threshold, "features": count}, "methylvi"))
    if tasks:
        terminal = {item["id"] for item in tasks}
        for item in tasks:
            terminal.difference_update(item["dependencies"])
        if delivery.get("enabled", True) and any(v for k, v in routes.items() if k != 'methylation_iteration'):
            weights = analysis.get("methylvi", {}).get("supervised_umap_weights", [0.2, 0.5, 0.7, 0.9])
            if (not isinstance(weights, list) or not weights
                    or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in weights)
                    or len(set(weights)) != len(weights)):
                raise WorkflowError("supervised_umap_weights must be unique numbers in [0, 1]")
            reuse = delivery.get("source_runs", {})
            if not isinstance(reuse, dict) or any(
                    not isinstance(v, dict) or set(v) != {"run_id", "task_id"}
                    or any(not isinstance(x, str) or not x or "/" in x or x in {".", ".."} for x in v.values())
                    for v in reuse.values()):
                raise WorkflowError("figures_comparison.source_runs must map task IDs to run_id/task_id")
            if not set(reuse) <= {x["id"] for x in tasks}:
                raise WorkflowError("figures_comparison.source_runs names an unplanned task")
            if not isinstance(delivery.get("legend_single_line", True), bool):
                raise WorkflowError("figures_comparison.legend_single_line must be boolean")
            spec = {"routes": routes, "weights": weights, "source_runs": reuse,
                    "legend_single_line": delivery.get("legend_single_line", True),
                    "allcools_max_features": max(feature_targets) if routes.get("allcools") else None,
                    "models": [{"id": x["id"], "parameters": x["parameters"]} for x in tasks],
                    "supervised_target_key": "cell_type"}
            tasks.append(task("figures_comparison", "plot", sorted(terminal), spec,
                              environment="scanpy_allcools"))
            terminal = {"figures_comparison"}
        tasks.append(task("workflow_summary", "summary", sorted(terminal)))
    validate_dag(tasks)
    return tasks


def required_environment_stages(tasks: List[dict]) -> set[str]:
    return {stage for item in tasks for stage in item.get("required_environments", [item["environment"]])}


def plan(project: Path, routes_option: str, run_id: str) -> dict:
    from audit_runtime import require_contract
    require_contract(project)
    if not run_id.strip() or "/" in run_id or run_id in {".", ".."}:
        raise WorkflowError("run-id must be a non-empty path-safe name")
    validate_run_id(run_id)
    cfg = load_project(project)
    if routes_option == "auto":
        preflight = validate(project)
        if preflight["status"] != "valid":
            raise WorkflowError("preflight failed: %s" % "; ".join(preflight["errors"]))
        available = preflight["routes"]
        selected = dict(available)
    else:
        requested = {item.strip() for item in routes_option.split(",") if item.strip()}
        unknown = requested - {"scanpy", "methscan_vmr", "methscan_dmr", "allcools",
                               "methylvi_allcools", "methylvi_vmr", "methylvi_vmr_dmr", "methylation_iteration"}
        if unknown:
            raise WorkflowError("unknown routes: %s" % ", ".join(sorted(unknown)))
        selected = close_routes({name: name in requested for name in {
            "scanpy", "methscan_vmr", "methscan_dmr", "allcools", "methylvi_allcools",
            "methylvi_vmr", "methylvi_vmr_dmr", "methylation_iteration",
        }})
        candidate_tasks = make_tasks(selected, cfg["analysis"])
        preflight = validate(project, required_stages=required_environment_stages(candidate_tasks),
                             selected_routes={name for name, enabled in selected.items() if enabled})
        if preflight["status"] != "valid":
            raise WorkflowError("preflight failed: %s" % "; ".join(preflight["errors"]))
        available = preflight["routes"]
        blocked = {name for name in requested if not available.get(name)}
        if blocked:
            raise WorkflowError("routes lack required inputs: %s" % ", ".join(sorted(blocked)))
        newly_blocked = {name for name, enabled in selected.items() if enabled and not available.get(name)}
        if newly_blocked:
            raise WorkflowError("route prerequisites lack required inputs: %s" % ", ".join(sorted(newly_blocked)))
    tasks = make_tasks(selected, cfg["analysis"])
    if not tasks:
        raise WorkflowError("no executable task was selected")
    commands = cfg["analysis"].get("task_commands") or {}
    missing = [item["id"] for item in tasks if not task_is_implemented(item["id"], commands)]
    if missing:
        raise WorkflowError("workflow contains tasks without an implementation: %s" % ", ".join(missing))
    root = Path(project).resolve()
    category = infer_category(selected, cfg["analysis"])
    result_dir = require_unused_result(root, run_id, category)
    validate_output_commands(commands)
    for item in tasks:
        if item['id'].startswith('methylation_iter_'):
            from scautopilot.review.methylation import source_evidence
            item['parameters']['source_evidence'] = source_evidence(root, item['parameters']['spec'])
    run_dir = root / ".workflow" / "runs" / run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise WorkflowError("refusing existing non-empty run directory: %s" % run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    template_lock_path = root / ".workflow" / "template-lock.json"
    template_lock = json.loads(template_lock_path.read_text(encoding="utf-8")) if template_lock_path.is_file() else None
    payload = {
        "schema_version": 1, "run_id": run_id, "project": str(root),
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "planned",
        "routes": selected, "input_signature": preflight["input_signature"],
        "code_signature": preflight.get("code_signature"),
        "runtime_identity": runtime_identity(root), "plan_identity_version": 2,
        "git_commit": git_commit(root), "template_lock": template_lock,
        "result_layout_version": 2, "result_category": category,
        "delivery_contract": "rna_full_v2" if selected.get("scanpy") else None,
        "result_dir": str(result_dir), "tasks": tasks,
    }
    write_json(run_dir / "preflight.json", preflight)
    write_json(run_dir / "plan.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--routes", default="auto")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = plan(args.project, args.routes, args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (WorkflowError, OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
