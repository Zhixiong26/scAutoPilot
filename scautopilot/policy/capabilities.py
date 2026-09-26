"""Machine-readable authorization boundary derived from plan.md section 4.1.

The dependency registry says what the implementation reads.  It must never be
able to grant itself permission to search a parameter, so authorization lives
in this separately versioned, packaged policy and is intersected with the
frozen session request.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Iterable


class CapabilityError(RuntimeError):
    """The packaged policy or a requested search space is invalid."""


@dataclass(frozen=True)
class CapabilityPolicy:
    version: int
    searchable: FrozenSet[str]
    rendering: FrozenSet[str]
    session_opt_in: FrozenSet[str]
    digest: str

    @classmethod
    def load_default(cls) -> "CapabilityPolicy":
        return cls.load(Path(__file__).with_name("capabilities.json"))

    @classmethod
    def load(cls, path: Path) -> "CapabilityPolicy":
        raw = Path(path).read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        allowed = {"schema_version", "searchable", "rendering", "session_opt_in"}
        unknown = set(payload) - allowed
        if unknown:
            raise CapabilityError("unknown capability-policy key(s): %s" % ", ".join(sorted(unknown)))
        if payload.get("schema_version") != 1:
            raise CapabilityError("unsupported capability-policy schema_version")
        groups = [payload.get(name, []) for name in ("searchable", "rendering", "session_opt_in")]
        if any(not isinstance(group, list) or not all(isinstance(x, str) for x in group) for group in groups):
            raise CapabilityError("capability groups must be lists of parameter IDs")
        searchable, rendering, opt_in = map(frozenset, groups)
        overlap = (searchable & rendering) | (searchable & opt_in) | (rendering & opt_in)
        if overlap:
            raise CapabilityError("capability classes overlap: %s" % ", ".join(sorted(overlap)))
        return cls(1, searchable, rendering, opt_in, hashlib.sha256(raw).hexdigest())

    def effective_search_space(self, registry, requested: Iterable[str]) -> FrozenSet[str]:
        """Return PackagedCapabilities ∩ RegistryImplemented ∩ SessionRequested.

        Refuse rather than silently shrink a request: a frozen session that
        claims to search three axes must not execute only two of them.
        """
        requested_set = frozenset(requested)
        unauthorized = requested_set - self.searchable
        if unauthorized:
            raise CapabilityError("session requested unauthorized parameter(s): %s" % ", ".join(sorted(unauthorized)))
        registry.assert_mutable(requested_set)
        return requested_set
