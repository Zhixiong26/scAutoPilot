"""Strict decision backends plus an explicit uncalibrated fallback."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


PARAMETERS = ("n_pcs", "n_neighbors", "resolution", "min_dist", "none", "escalate")
DIRECTIONS = ("increase", "decrease", "keep")
QUALITY = ("poor", "weak", "acceptable", "good", "excellent")


class BackendError(RuntimeError):
    pass


def _probability(value: Any, name: str) -> float:
    number = float(value)
    if not 0 <= number <= 1:
        raise BackendError("%s must lie in [0, 1]" % name)
    return number


def _distribution(value: Any, allowed: Sequence[str], name: str) -> Dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(allowed):
        raise BackendError("%s keys must be exactly %s" % (name, ", ".join(allowed)))
    result = {key: _probability(value[key], "%s.%s" % (name, key)) for key in allowed}
    if abs(sum(result.values()) - 1.0) > 1e-6:
        raise BackendError("%s probabilities must sum to one" % name)
    return result


def validate_judgments(value: Any, backend: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise BackendError("decision backend response must be a JSON object")
    allowed = {"accept_probability", "parameter", "direction", "quality", "escalate_probability"}
    unknown = set(value) - allowed
    missing = allowed - set(value)
    if unknown or missing:
        raise BackendError("decision backend response schema mismatch; missing=%s unknown=%s" %
                           (sorted(missing), sorted(unknown)))
    return {
        "backend": backend,
        "accept_probability": _probability(value["accept_probability"], "accept_probability"),
        "parameter": _distribution(value["parameter"], PARAMETERS, "parameter"),
        "direction": _distribution(value["direction"], DIRECTIONS, "direction"),
        "quality": _distribution(value["quality"], QUALITY, "quality"),
        "escalate_probability": _probability(value["escalate_probability"], "escalate_probability"),
    }


def command_backend(command: Any, request: Mapping[str, Any], timeout: float = 120.0) -> Dict[str, Any]:
    argv = shlex.split(command) if isinstance(command, str) else [str(item) for item in command]
    if not argv:
        raise BackendError("decision command is empty")
    try:
        completed = subprocess.run(argv, input=json.dumps(request).encode("utf-8"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackendError("decision command could not complete: %s" % exc)
    if completed.returncode:
        raise BackendError("decision command failed (%d): %s" %
                           (completed.returncode, completed.stderr.decode("utf-8", "replace")[-2000:]))
    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except ValueError as exc:
        raise BackendError("decision command returned invalid JSON: %s" % exc)
    return validate_judgments(response, "command_backend")


def _decision_python(project: Path, settings: Mapping[str, Any]) -> str:
    configured = str(settings.get("python") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise BackendError("configured decision Python does not exist: %s" % path)
        return str(path)
    manifest = project / "config" / "environments.tsv"
    if manifest.is_file():
        import csv
        with manifest.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row.get("stage") == "decision" and row.get("python"):
                    path = Path(row["python"]).expanduser()
                    if not path.is_file():
                        raise BackendError("decision environment Python does not exist: %s" % path)
                    return str(path)
    if sys.version_info >= (3, 10):
        return sys.executable
    raise BackendError("system-one-adapter requires Python >=3.10; provision the decision environment")


def system_one_adapter_backend(
    project: Path,
    mode: str,
    settings: Mapping[str, Any],
    request: Mapping[str, Any],
    timeout: float = 180.0,
) -> Dict[str, Any]:
    """Invoke the official adapter in its isolated Python >=3.10 environment."""
    if mode not in {"system_one_local", "system_one_commercial"}:
        raise BackendError("unsupported system-one-adapter mode: %s" % mode)
    if mode == "system_one_local" and (not settings.get("base_url") or not settings.get("model")):
        raise BackendError("system_one_local is selected but base_url/model is not configured")
    if mode == "system_one_commercial" and (not settings.get("provider") or not settings.get("model")):
        raise BackendError("system_one_commercial is selected but provider/model is not configured")
    python = _decision_python(Path(project), settings)
    runner = Path(project) / "tools" / "system_one_adapter_runner.py"
    if not runner.is_file():
        repository_runner = Path(__file__).resolve().parents[2] / "scripts" / "system_one_adapter_runner.py"
        runner = repository_runner if repository_runner.is_file() else runner
    if not runner.is_file():
        raise BackendError("system-one-adapter runner is absent: %s" % runner)
    payload = {"schema_version": 1, "mode": mode, "settings": dict(settings), "request": dict(request)}
    try:
        completed = subprocess.run(
            [python, str(runner)], input=json.dumps(payload).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackendError("system-one-adapter runner could not complete: %s" % exc)
    if completed.returncode:
        raise BackendError("system-one-adapter runner failed (%d): %s" %
                           (completed.returncode, completed.stderr.decode("utf-8", "replace")[-4000:]))
    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except ValueError as exc:
        raise BackendError("system-one-adapter runner returned invalid JSON: %s" % exc)
    if not isinstance(response, dict) or not isinstance(response.get("judgments"), dict):
        raise BackendError("system-one-adapter runner response lacks judgments")
    result = validate_judgments(response["judgments"], mode)
    result["audit"] = response.get("audit") or {}
    return result


def _one_hot(options: Sequence[str], selected: str) -> Dict[str, float]:
    return {option: 1.0 if option == selected else 0.0 for option in options}


def rule_fallback(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Uncalibrated fallback; it is never reported as Jev."""
    embedding = state["embedding"]
    clustering = state["clustering"]
    biology = state["biology"]
    batch = state["batch"]
    trust = embedding.get("trustworthiness")
    knn = embedding.get("knn_preservation")
    silhouette = clustering.get("silhouette")
    celltype = biology.get("celltype_asw") if biology.get("independent") else None
    ilisi = batch.get("ilisi")
    acceptable = (trust is not None and trust >= 0.95 and knn is not None and knn >= 0.75
                  and silhouette is not None and silhouette >= 0.15
                  and (celltype is None or celltype >= 0.20)
                  and (ilisi is None or ilisi >= 0.35))
    if silhouette is not None and silhouette < 0.15:
        parameter, direction = "resolution", "increase"
    elif ilisi is not None and ilisi < 0.35:
        parameter, direction = "n_neighbors", "increase"
    elif trust is not None and trust < 0.95:
        parameter, direction = "n_pcs", "increase"
    elif knn is not None and knn < 0.75:
        parameter, direction = "min_dist", "decrease"
    else:
        parameter, direction = "none", "keep"
    available = [value for value in (trust, knn, (silhouette + 1) / 2 if silhouette is not None else None,
                                      (celltype + 1) / 2 if celltype is not None else None)
                 if value is not None]
    mean = sum(available) / len(available) if available else 0.0
    quality = "poor" if mean < 0.35 else "weak" if mean < 0.50 else "acceptable" if mean < 0.65 else "good" if mean < 0.82 else "excellent"
    return validate_judgments({
        "accept_probability": 1.0 if acceptable else 0.0,
        "parameter": _one_hot(PARAMETERS, parameter),
        "direction": _one_hot(DIRECTIONS, direction),
        "quality": _one_hot(QUALITY, quality),
        "escalate_probability": 0.0,
    }, "uncalibrated_rule_fallback_v0")
