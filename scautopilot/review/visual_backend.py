"""Strict multimodal backends for visual observations, never decisions."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping

from .backend import BackendError, _decision_python
from .visual import VisualEvidenceError, validate_observations


def _validate_response(value: Any, figures) -> Dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("observations"), list):
        raise BackendError("visual backend response must contain an observations list")
    try:
        observations = validate_observations(value["observations"])
    except VisualEvidenceError as exc:
        raise BackendError(str(exc))
    available = {item["figure_id"] for item in figures}
    cited = {figure for item in observations for figure in item["figure_ids"]}
    unknown = sorted(cited - available)
    if unknown:
        raise BackendError("visual backend cited unavailable figures: %s" % ", ".join(unknown))
    return {"observations": observations, "audit": value.get("audit") or {}}


def visual_command_backend(command: Any, request: Mapping[str, Any], timeout: float) -> Dict[str, Any]:
    argv = shlex.split(command) if isinstance(command, str) else [str(item) for item in command]
    if not argv:
        raise BackendError("visual decision command is empty")
    try:
        completed = subprocess.run(argv, input=json.dumps(request).encode("utf-8"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackendError("visual command could not complete: %s" % exc)
    if completed.returncode:
        raise BackendError("visual command failed (%d): %s" %
                           (completed.returncode, completed.stderr.decode("utf-8", "replace")[-4000:]))
    try:
        value = json.loads(completed.stdout.decode("utf-8"))
    except ValueError as exc:
        raise BackendError("visual command returned invalid JSON: %s" % exc)
    return _validate_response(value, request.get("figures") or [])

def openai_compatible_visual_backend(project: Path, settings: Mapping[str, Any],
                                      request: Mapping[str, Any], timeout: float) -> Dict[str, Any]:
    if not settings.get("base_url") or not settings.get("model") or not settings.get("api_key_env"):
        raise BackendError("openai_compatible visual backend requires base_url, model, and api_key_env")
    python = _decision_python(Path(project), settings)
    runner = Path(project) / "tools" / "visual_vlm_runner.py"
    if not runner.is_file():
        repository_runner = Path(__file__).resolve().parents[2] / "scripts" / "visual_vlm_runner.py"
        runner = repository_runner if repository_runner.is_file() else runner
    if not runner.is_file():
        raise BackendError("visual VLM runner is absent: %s" % runner)
    payload = {"schema_version": 1, "settings": dict(settings), "request": dict(request)}
    try:
        completed = subprocess.run([python, str(runner)], input=json.dumps(payload).encode("utf-8"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackendError("visual VLM runner could not complete: %s" % exc)
    if completed.returncode:
        raise BackendError("visual VLM runner failed (%d): %s" %
                           (completed.returncode, completed.stderr.decode("utf-8", "replace")[-4000:]))
    try:
        value = json.loads(completed.stdout.decode("utf-8"))
    except ValueError as exc:
        raise BackendError("visual VLM runner returned invalid JSON: %s" % exc)
    return _validate_response(value, request.get("figures") or [])
