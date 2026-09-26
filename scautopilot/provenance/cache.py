"""Canonical cache identity from plan.md section 4.2."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Sequence


class CacheIdentityError(RuntimeError):
    pass


def build_cache_key(
    *,
    tool_implementation_digest: str,
    effective_parameters: Mapping[str, Any],
    upstream_artifact_checksums: Sequence[str],
    environment_fingerprint: str,
    seed: Optional[int],
    registry_version: str,
    contract_schema_version: int,
) -> str:
    """Hash every input that can change a cached scientific artifact.

    Ordered upstream checksums are intentional: changing input order can change
    concatenation, batches, and floating-point reduction order.
    """
    required = {
        "tool_implementation_digest": tool_implementation_digest,
        "environment_fingerprint": environment_fingerprint,
        "registry_version": registry_version,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        raise CacheIdentityError("cannot cache without %s" % ", ".join(sorted(missing)))
    if any(not str(value).strip() for value in upstream_artifact_checksums):
        raise CacheIdentityError("upstream artifact checksums must be non-empty")
    payload = {
        "contract_schema_version": int(contract_schema_version),
        "effective_parameters": effective_parameters,
        "environment_fingerprint": environment_fingerprint,
        "registry_version": registry_version,
        "seed": seed,
        "tool_implementation_digest": tool_implementation_digest,
        "upstream_artifact_checksums": list(upstream_artifact_checksums),
    }
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CacheIdentityError("cache identity is not canonical JSON: %s" % exc) from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
