#!/usr/bin/env python3
"""Run official system-one-adapter and emit strict scAutoPilot judgments."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Mapping
from urllib.parse import urlparse


def _load_input() -> Dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except ValueError as exc:
        raise RuntimeError("stdin is not valid JSON: %s" % exc)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("unsupported runner request schema")
    return value


def _question_models(request: Mapping[str, Any]):
    from system_one_adapter import Choice, Noul, Score

    result = {}
    for question in request.get("judgments") or []:
        identifier = question.get("id")
        primitive = str(question.get("primitive") or "").lower()
        instructions = str(question.get("instructions") or "")
        if not identifier or not instructions:
            raise RuntimeError("every judgment needs id and instructions")
        if primitive == "noul":
            result[identifier] = Noul(instructions=instructions)
        elif primitive == "choice":
            criteria = question.get("criteria")
            if not isinstance(criteria, dict):
                raise RuntimeError("Choice %s lacks criteria" % identifier)
            result[identifier] = Choice(instructions=instructions, criteria=criteria)
        elif primitive == "score":
            levels = question.get("levels")
            if not isinstance(levels, list):
                raise RuntimeError("Score %s lacks levels" % identifier)
            result[identifier] = Score(instructions=instructions, criteria=levels)
        else:
            raise RuntimeError("unknown primitive %r" % primitive)
    return result


def _probabilities(answer: Mapping[str, Any], allowed) -> Dict[str, float]:
    values = answer.get("probabilities")
    if not isinstance(values, dict):
        raise RuntimeError("adapter answer lacks probabilities")
    result = {}
    for index, label in enumerate(allowed):
        value = values.get(label, values.get(str(index), values.get(index)))
        if value is None:
            raise RuntimeError("adapter answer lacks probability for %s" % label)
        result[str(label)] = float(value)
    return result


def response_to_payload(response: Any, mode: str, settings: Mapping[str, Any]) -> Dict[str, Any]:
    dumped = response.model_dump(mode="json")
    answers = dumped.get("answers") or {}
    quality_levels = ["poor", "weak", "acceptable", "good", "excellent"]
    parameters = ["n_pcs", "n_neighbors", "resolution", "min_dist", "none", "escalate"]
    directions = ["increase", "decrease", "keep"]
    judgments = {
        "accept_probability": float(answers["accept"]["noul"]),
        "parameter": _probabilities(answers["parameter"], parameters),
        "direction": _probabilities(answers["direction"], directions),
        "quality": _probabilities(answers["quality"], quality_levels),
        "escalate_probability": float(answers["escalate"]["noul"]),
    }
    safe_settings = {key: value for key, value in settings.items() if key != "api_key"}
    audit = {
        "backend": mode,
        "adapter": "system-one-adapter",
        "settings": safe_settings,
        "usage": dumped.get("usage"),
        "response": dumped,
    }
    return {"judgments": judgments, "audit": audit}


def _run(payload: Mapping[str, Any]) -> Dict[str, Any]:
    from system_one_adapter import SystemOneAdapterClient, __version__

    mode = str(payload.get("mode") or "")
    settings = payload.get("settings") or {}
    request = payload.get("request") or {}
    questions = _question_models(request)
    common = {
        "structured_outputs": bool(settings.get("structured_outputs", False)),
        "llm_answer_mode": "probabilities",
        "normalize_probabilities": bool(settings.get("normalize_probabilities", True)),
        "n_retry_malformed_structure": int(settings.get("n_retry_malformed_structure", 2)),
    }
    if mode == "system_one_local":
        from system_one_adapter.providers.openai import OpenAIProvider

        base_url = str(settings.get("base_url") or "").rstrip("/")
        model = str(settings.get("model") or "")
        if not base_url or not model:
            raise RuntimeError("system_one_local requires base_url and model")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError("system_one_local base_url must be an HTTP(S) URL")
        key_name = str(settings.get("api_key_env") or "SCAUTOPILOT_LOCAL_LLM_API_KEY")
        # The OpenAI SDK requires a non-empty key even when a local vLLM endpoint
        # performs no authentication.  This placeholder is never sent elsewhere.
        api_key = os.environ.get(key_name) or "local-no-auth"
        provider = OpenAIProvider(model, base_url=base_url, api_key=api_key,
                                  api=str(settings.get("api") or "chat_completions"))
        try:
            with SystemOneAdapterClient(model=provider, **common) as client:
                response = client.system_one(state=request["state_payload"], questions=questions)
        finally:
            provider.close()
    elif mode == "system_one_commercial":
        provider_name = str(settings.get("provider") or "")
        model = str(settings.get("model") or "")
        if provider_name not in {"openai", "anthropic", "gemini", "openai_compatible"} or not model:
            raise RuntimeError("commercial backend requires provider and model")
        if provider_name == "openai_compatible":
            from system_one_adapter.providers.openai import OpenAIProvider

            base_url = str(settings.get("base_url") or "").rstrip("/")
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise RuntimeError("commercial openai_compatible backend requires an HTTP(S) base_url")
            key_name = str(settings.get("api_key_env") or "")
            api_key = os.environ.get(key_name) if key_name else None
            if not api_key:
                raise RuntimeError("commercial openai_compatible backend requires its configured API key environment variable")
            provider = OpenAIProvider(model, base_url=base_url, api_key=api_key,
                                      api=str(settings.get("api") or "chat_completions"))
            try:
                with SystemOneAdapterClient(model=provider, **common) as client:
                    response = client.system_one(state=request["state_payload"], questions=questions)
            finally:
                provider.close()
        else:
            with SystemOneAdapterClient(provider=provider_name, model=model, **common) as client:
                response = client.system_one(state=request["state_payload"], questions=questions)
    else:
        raise RuntimeError("unsupported backend mode: %s" % mode)
    result = response_to_payload(response, mode, settings)
    result["audit"]["adapter_version"] = __version__
    return result


def main() -> int:
    print(json.dumps(_run(_load_input()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
