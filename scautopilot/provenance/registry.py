"""The parameter -> artifact dependency registry (plan.md section 4.1).

Section 4 states that invalidation is derived from one artifact DAG and that no
second, hand-maintained invalidation rule may exist. That statement needs a
concrete artifact or it stays a wish: without one, every route plugin eventually
grows its own `if n_neighbors changed: rerun`, and the two rule sets drift until
a cache hit is no longer trustworthy.

So the registry is the single source of invalidation truth, and the invalidation
matrix in the plan is *generated* from it rather than maintained beside it. Two
consequences are load-bearing:

* **Unknown means frozen.** A parameter absent from the registry is refused
  before execution (section 12), which is what makes "the search space is what
  the plan declared" checkable rather than aspirational.
* **Evidence is required.** Every entry cites where the parameter is read and
  which test covers it. An entry without evidence is an unverified claim, and
  the whole point of the registry is that its claims can be rechecked against
  the code that implements them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = 1
RELATIONS = ("upstream",)


class RegistryError(RuntimeError):
    """The registry is malformed, or a request contradicts it."""


@dataclass(frozen=True)
class Artifact:
    """One artifact node. `upstream` are its direct inputs, not its consumers."""

    artifact_id: str
    produced_by: str
    upstream: Tuple[str, ...] = ()
    kind: str = ""


@dataclass(frozen=True)
class ParameterEntry:
    """One tunable parameter and the artifacts it directly determines.

    `affects` lists *direct* effects only. Downstream reach is a property of the
    artifact DAG, so it is computed rather than written down: a hand-written
    closure is exactly the second rule set section 4 forbids.
    """

    parameter_id: str
    stage: str
    affects: Tuple[str, ...]
    read: Tuple[str, ...]
    tests: Tuple[str, ...] = ()
    default: Any = None
    verified_against: str = ""
    note: str = ""
    # Fail closed. Search is an explicit opt-in backed by a packaged capability
    # policy and a behavioural test; merely documenting a read site is not an
    # authorization to mutate it.
    searchable: bool = False


class ParameterRegistry:
    """Loads the registry, checks it, and answers invalidation questions."""

    def __init__(
        self,
        artifacts: Mapping[str, Artifact],
        parameters: Mapping[str, ParameterEntry],
        tool_versions: Mapping[str, str],
        schema_version: int = SCHEMA_VERSION,
        frozen: Optional[Mapping[str, str]] = None,
    ):
        self.artifacts: Dict[str, Artifact] = dict(artifacts)
        self.parameters: Dict[str, ParameterEntry] = dict(parameters)
        self.tool_versions: Dict[str, str] = dict(tool_versions)
        self.frozen: Dict[str, str] = dict(frozen or {})
        self.schema_version = schema_version
        self._downstream: Optional[Dict[str, FrozenSet[str]]] = None
        self._affected: Dict[str, FrozenSet[str]] = {}

    # --- construction -------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "ParameterRegistry":
        """Read YAML, or JSON-compatible YAML when PyYAML is unavailable.

        The loader mirrors `scripts/_common.load_structured` on purpose: the
        control plane and the generator should fail the same way on the same
        file, rather than one of them accepting a document the other rejects.
        """
        path = Path(path).resolve()
        text = path.read_text(encoding="utf-8")
        try:
            import yaml  # type: ignore
        except ImportError:
            try:
                payload = json.loads(text)
            except ValueError as exc:
                raise RegistryError(
                    "%s requires PyYAML unless it is JSON-compatible YAML: %s" % (path, exc)
                )
        else:
            payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise RegistryError("registry root must be a mapping: %s" % path)
        registry = cls.from_mapping(payload)
        registry.validate()
        return registry

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ParameterRegistry":
        version = payload.get("schema_version")
        if version is None:
            raise RegistryError("registry: missing schema_version")
        if int(version) != SCHEMA_VERSION:
            raise RegistryError(
                "registry: schema_version %s cannot be read as version %s" % (version, SCHEMA_VERSION)
            )
        unknown = sorted(set(payload) - {"schema_version", "artifacts", "parameters", "tools", "frozen"})
        if unknown:
            raise RegistryError("registry: unknown top-level key(s) %s" % ", ".join(unknown))

        # `frozen` names parameters the plan declares searchable that the code
        # does not actually expose. Recording them beats omitting them: an
        # omitted parameter and an examined-and-refused one look identical in a
        # bare parameter list, and the difference is whether anyone checked.
        frozen = payload.get("frozen") or {}
        for parameter_id, reason in frozen.items():
            if not isinstance(reason, str) or not reason.strip():
                raise RegistryError(
                    "registry.frozen.%s: needs a reason, otherwise a frozen parameter "
                    "is indistinguishable from an overlooked one" % parameter_id
                )

        artifacts: Dict[str, Artifact] = {}
        for artifact_id, spec in (payload.get("artifacts") or {}).items():
            if not isinstance(spec, dict):
                raise RegistryError("registry.artifacts.%s: expected a mapping" % artifact_id)
            extra = sorted(set(spec) - {"produced_by", "upstream", "kind"})
            if extra:
                raise RegistryError(
                    "registry.artifacts.%s: unknown key(s) %s" % (artifact_id, ", ".join(extra))
                )
            if not spec.get("produced_by"):
                raise RegistryError("registry.artifacts.%s: produced_by is required" % artifact_id)
            artifacts[artifact_id] = Artifact(
                artifact_id=artifact_id,
                produced_by=str(spec["produced_by"]),
                upstream=tuple(spec.get("upstream") or ()),
                kind=str(spec.get("kind", "")),
            )

        parameters: Dict[str, ParameterEntry] = {}
        for parameter_id, spec in (payload.get("parameters") or {}).items():
            if not isinstance(spec, dict):
                raise RegistryError("registry.parameters.%s: expected a mapping" % parameter_id)
            extra = sorted(
                set(spec)
                - {
                    "stage",
                    "affects",
                    "read",
                    "tests",
                    "default",
                    "verified_against",
                    "note",
                    "searchable",
                }
            )
            if extra:
                raise RegistryError(
                    "registry.parameters.%s: unknown key(s) %s" % (parameter_id, ", ".join(extra))
                )
            parameters[parameter_id] = ParameterEntry(
                parameter_id=parameter_id,
                stage=str(spec.get("stage", "")),
                affects=tuple(spec.get("affects") or ()),
                read=tuple(spec.get("read") or ()),
                tests=tuple(spec.get("tests") or ()),
                default=spec.get("default"),
                verified_against=str(spec.get("verified_against", "")),
                note=str(spec.get("note", "")),
                searchable=bool(spec.get("searchable", False)),
            )

        return cls(
            artifacts,
            parameters,
            payload.get("tools") or {},
            schema_version=int(version),
            frozen=frozen,
        )

    # --- integrity ----------------------------------------------------------

    def validate(self) -> None:
        """Reject a registry that could produce a wrong invalidation."""
        problems: List[str] = []
        for artifact in self.artifacts.values():
            for upstream in artifact.upstream:
                if upstream not in self.artifacts:
                    problems.append(
                        "artifact %s lists unknown upstream %s" % (artifact.artifact_id, upstream)
                    )
        for entry in self.parameters.values():
            if not entry.stage:
                problems.append("parameter %s has no stage" % entry.parameter_id)
            if not entry.affects:
                problems.append(
                    "parameter %s affects nothing; a parameter with no effect is not tunable"
                    % entry.parameter_id
                )
            if not entry.read:
                problems.append(
                    "parameter %s cites no read site; unverified entries do not belong in the registry"
                    % entry.parameter_id
                )
            if entry.searchable and not entry.tests:
                problems.append(
                    "parameter %s is searchable but cites no behavioural test; documented "
                    "implementation is not enough to authorize automatic mutation"
                    % entry.parameter_id
                )
            for artifact_id in entry.affects:
                if artifact_id not in self.artifacts:
                    problems.append(
                        "parameter %s affects unknown artifact %s" % (entry.parameter_id, artifact_id)
                    )
            if entry.verified_against and entry.verified_against not in self.tool_versions:
                problems.append(
                    "parameter %s verified against unknown tool %s"
                    % (entry.parameter_id, entry.verified_against)
                )
        cycle = self._find_cycle()
        if cycle:
            problems.append("artifact DAG has a cycle: %s" % " -> ".join(cycle))
        if problems:
            raise RegistryError("; ".join(problems))

    def _find_cycle(self) -> Optional[List[str]]:
        """Return one cycle in the artifact DAG, if any.

        A cyclic artifact graph makes "transitive closure" meaningless: every
        member invalidates every other, so the cache would either never hit or,
        worse, hit when it must not.
        """
        WHITE, GREY, BLACK = 0, 1, 2
        colour: Dict[str, int] = {a: WHITE for a in self.artifacts}
        stack: List[str] = []

        def visit(node: str) -> Optional[List[str]]:
            colour[node] = GREY
            stack.append(node)
            for upstream in self.artifacts[node].upstream:
                if upstream not in self.artifacts:
                    # A dangling reference is already a reported problem; walking
                    # through it here would crash the check that reports it.
                    continue
                if colour[upstream] == GREY:
                    return stack[stack.index(upstream):] + [upstream]
                if colour[upstream] == WHITE:
                    found = visit(upstream)
                    if found:
                        return found
            stack.pop()
            colour[node] = BLACK
            return None

        for node in self.artifacts:
            if colour[node] == WHITE:
                found = visit(node)
                if found:
                    return found
        return None

    # --- queries ------------------------------------------------------------

    def downstream(self, artifact_id: str) -> FrozenSet[str]:
        """Everything that must be recomputed when `artifact_id` changes.

        Direction matters: the DAG stores upstream edges, while invalidation
        travels to consumers. Consumers are therefore derived once and cached.
        """
        if self._downstream is None:
            consumers: Dict[str, Set[str]] = {a: set() for a in self.artifacts}
            for artifact in self.artifacts.values():
                for upstream in artifact.upstream:
                    consumers[upstream].add(artifact.artifact_id)
            self._downstream = {a: frozenset(c) for a, c in consumers.items()}
        if artifact_id not in self.artifacts:
            raise RegistryError("unknown artifact: %s" % artifact_id)
        seen: Set[str] = set()
        frontier = [artifact_id]
        while frontier:
            node = frontier.pop()
            for consumer in self._downstream.get(node, ()):
                if consumer not in seen:
                    seen.add(consumer)
                    frontier.append(consumer)
        return frozenset(seen)

    def is_registered(self, parameter_id: str) -> bool:
        return parameter_id in self.parameters

    def frozen_reason(self, parameter_id: str) -> Optional[str]:
        """Why a declared-but-unavailable parameter is frozen, if it was examined."""
        return self.frozen.get(parameter_id)

    def affected_artifacts(self, parameter_id: str) -> FrozenSet[str]:
        """`transitive_closure(direct_artifacts(p))` from plan.md section 4.1."""
        cached = self._affected.get(parameter_id)
        if cached is not None:
            return cached
        entry = self.parameters.get(parameter_id)
        if entry is None:
            raise RegistryError(
                "parameter %s is not registered; unregistered parameters are frozen (section 12)"
                % parameter_id
            )
        reach: Set[str] = set()
        for artifact_id in entry.affects:
            reach.add(artifact_id)
            reach |= self.downstream(artifact_id)
        result = frozenset(reach)
        self._affected[parameter_id] = result
        return result

    def invalidated_artifacts(self, changed: Mapping[str, Any]) -> FrozenSet[str]:
        """The recomputation set for a candidate's parameter diff.

        This is the function the optimizer and the cache both call, so a change
        and the work it implies cannot disagree. Values are accepted but unused:
        what matters is *which* parameters moved, not to what, because the
        registry records reach rather than a value-indexed rule.
        """
        reach: Set[str] = set()
        for parameter_id in changed:
            reach |= self.affected_artifacts(parameter_id)
        return frozenset(reach)

    def assert_mutable(self, parameter_ids: Iterable[str]) -> None:
        """Refuse a change to anything outside the registered search space.

        Three distinct refusals, kept apart because they call for different
        responses. An unregistered name is unknown -- check the spelling, or
        audit and register it. A registered-but-closed parameter is traced and
        deliberately left alone, so opening it is a scope decision, not an audit
        one. A name in `frozen` was declared searchable by the plan and found
        absent in the code: that is an implementation gap, and no amount of
        registry editing will make the parameter take effect.
        """
        missing_gaps = [p for p in parameter_ids if p in self.frozen]
        if missing_gaps:
            raise RegistryError(
                "refusing to change unimplemented parameter(s): %s"
                % "; ".join("%s (%s)" % (p, self.frozen[p]) for p in missing_gaps)
            )
        closed = sorted(
            p for p in parameter_ids if self.is_registered(p) and not self.parameters[p].searchable
        )
        if closed:
            raise RegistryError(
                "refusing to change closed parameter(s): %s. These are traced but held "
                "out of the search space; opening one is a scope change." % ", ".join(closed)
            )
        unknown = sorted(p for p in parameter_ids if not self.is_registered(p))
        if unknown:
            raise RegistryError(
                "refusing to change unregistered parameter(s): %s. "
                "Unregistered parameters are frozen; open them by adding a verified "
                "registry entry, not by relaxing this check." % ", ".join(unknown)
            )

    def stale_entries(self, current_tool_versions: Mapping[str, str]) -> Dict[str, str]:
        """Entries whose verification no longer matches the tool they were checked against.

        Section 4.1 treats a cross-version entry as *to be revalidated*, never as
        silently inherited: the code may read the parameter differently now, and
        the registry would keep asserting an old reach.
        """
        stale: Dict[str, str] = {}
        for entry in self.parameters.values():
            if not entry.verified_against:
                continue
            recorded = self.tool_versions.get(entry.verified_against)
            current = current_tool_versions.get(entry.verified_against)
            if current is not None and recorded is not None and current != recorded:
                stale[entry.parameter_id] = (
                    "verified against %s %s, environment has %s"
                    % (entry.verified_against, recorded, current)
                )
        return stale
