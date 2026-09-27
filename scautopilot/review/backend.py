"""Strict Jev command adapter plus an explicit uncalibrated fallback backend."""

from __future__ import annotations

import json
import shlex
import subprocess
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
        raise BackendError("Jev response must be a JSON object")
    allowed = {"accept_probability", "parameter", "direction", "quality", "escalate_probability"}
    unknown = set(value) - allowed
    missing = allowed - set(value)
    if unknown or missing:
        raise BackendError("Jev response schema mismatch; missing=%s unknown=%s" %
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
        raise BackendError("Jev command is empty")
    completed = subprocess.run(argv, input=json.dumps(request).encode("utf-8"),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout, check=False)
    if completed.returncode:
        raise BackendError("Jev command failed (%d): %s" %
                           (completed.returncode, completed.stderr.decode("utf-8", "replace")[-2000:]))
    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except ValueError as exc:
        raise BackendError("Jev command returned invalid JSON: %s" % exc)
    return validate_judgments(response, "jev_command")


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
