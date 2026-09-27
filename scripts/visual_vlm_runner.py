#!/usr/bin/env python3
"""Send a bounded fixed figure panel to an OpenAI-compatible vision model."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Mapping
from urllib.parse import urlparse


SYSTEM_PROMPT = """You are a visual sensor for auditable single-cell analysis figures.
Report only visible structural observations. Do not assign a global quality score, accept or
reject a candidate, change parameters, or infer unsupported biology. Return one JSON object
with exactly one key, observations. observations is a list; every item must have exactly:
observation_type, present, confidence, figure_ids, labels, description.
observation_type must be one of: sample_specific_islands, disconnected_same_label,
bridge_patterns, extreme_crowding, isolated_outlier_islands, possible_overfragmentation.
present is boolean; confidence is in [0,1]; figure_ids and labels are string lists;
description is concise. Cite only supplied figure IDs. Include meaningful negative observations
when visible. Output JSON only."""


def _load() -> Dict[str, Any]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("unsupported visual runner request schema")
    return value


def _json_content(text: str) -> Dict[str, Any]:
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("visual model did not return a JSON object")
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("visual model response is not a JSON object")
    return value


def _run(payload: Mapping[str, Any]) -> Dict[str, Any]:
    from openai import OpenAI

    settings = payload.get("settings") or {}
    request = payload.get("request") or {}
    base_url = str(settings.get("base_url") or "").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("visual backend base_url must be an HTTP(S) URL")
    model = str(settings.get("model") or "")
    key_name = str(settings.get("api_key_env") or "")
    api_key = os.environ.get(key_name) if key_name else None
    if not model or not api_key:
        raise RuntimeError("visual backend model or API key environment variable is missing")
    figures = request.get("figures") or []
    if not figures:
        raise RuntimeError("visual backend received no figures")
    content = [{"type": "text", "text": json.dumps({
        "task": "Inspect the supplied fixed panel under the schema in the system message.",
        "dataset": request.get("dataset") or {},
        "figures": [{key: item.get(key) for key in ("figure_id", "sha256", "width", "height")}
                    for item in figures],
    }, sort_keys=True)}]
    for item in figures:
        path = Path(str(item["path"]))
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append({"type": "text", "text": "figure_id=%s" % item["figure_id"]})
        content.append({"type": "image_url", "image_url": {
            "url": "data:%s;base64,%s" % (item.get("mime_type", "image/png"), encoded),
            "detail": str(settings.get("image_detail") or "low"),
        }})
    client = OpenAI(api_key=api_key, base_url=base_url,
                    timeout=float(settings.get("request_timeout_seconds", 120)))
    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": content}],
        "stream": False,
        "max_tokens": int(settings.get("max_output_tokens", 1600)),
    }
    if bool(settings.get("structured_outputs", False)):
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    raw = response.model_dump(mode="json")
    text = response.choices[0].message.content or ""
    parsed_response = _json_content(text)
    safe_settings = {key: value for key, value in settings.items() if key != "api_key"}
    usage = raw.get("usage") or {}
    return {
        "observations": parsed_response.get("observations"),
        "audit": {"backend": "openai_compatible", "model": model,
                  "settings": safe_settings, "usage": usage,
                  "response_id": raw.get("id"), "response_model": raw.get("model"),
                  "finish_reason": ((raw.get("choices") or [{}])[0]).get("finish_reason")},
    }


def main() -> int:
    print(json.dumps(_run(_load()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
