"""The shared objects of plan.md section 4, plus the state vocabularies of section 5.

Two properties matter more than the field lists:

* **Fail closed.** An unknown key is an error, not something to ignore. A record
  written by a newer engine must not be silently read as if the extra field were
  absent -- that is how two engines end up disagreeing about what a decision meant.
* **Versioned.** Every envelope carries `schema_version`. Records are never
  rewritten in place (section 13), so a reader has to be able to tell which
  contract a payload was written under.

`ComparisonProtocol` and `MultiFidelitySpec` carry real validation because they
gate admission rather than merely describing it: a candidate that cannot prove
protocol compatibility must not be ranked against one that can, and a fidelity
ladder that is not monotonic produces rankings that mean nothing across rungs.
"""

from __future__ import annotations

import dataclasses
import enum
import types
import typing
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = 1


class ContractError(RuntimeError):
    """A record violates its contract, or cannot be read under this schema version."""


# --- state vocabularies (plan.md section 5) ---------------------------------
#
# The four dimensions are deliberately separate. Dominated is not a scientific
# failure, not_promoted is not permanent invalidity, and a queued job is not a
# failed one; collapsing them into one "status" string is what makes a report
# claim a science result that only ever waited in a queue.


class ExecutionState(str, enum.Enum):
    PLANNED = "planned"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ScientificState(str, enum.Enum):
    INVALID = "invalid"
    CONSTRAINT_FAILED = "constraint_failed"
    FEASIBLE = "feasible"
    REVIEW_REQUIRED = "review_required"


class SessionState(str, enum.Enum):
    """Operational state, kept separate from scientific qualification."""

    ACTIVE = "active"
    PAUSED = "paused"
    BUDGET_BLOCKED = "budget_blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SearchState(str, enum.Enum):
    FRONTIER = "frontier"
    DOMINATED = "dominated"
    NOT_PROMOTED = "not_promoted"
    SELECTED_FOR_CONFIRMATION = "selected_for_confirmation"


class PublishState(str, enum.Enum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    CONFIRMED = "confirmed"


class MetricStatus(str, enum.Enum):
    """Whether a metric number means anything at all (section 7.1).

    A missing required metric is not a zero and not a pass: a candidate whose
    required metric is `unavailable` cannot be declared to meet the goal.
    """

    OK = "ok"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class ConstraintSeverity(str, enum.Enum):
    """Maps onto ScientificState at the constraint funnel (section 8)."""

    INTEGRITY = "integrity"
    SCIENTIFIC = "scientific"
    PROTECTED = "protected"


class ObservationStatus(str, enum.Enum):
    ACTIVE = "active"
    NEEDS_REVALIDATION = "needs_revalidation"
    SUPERSEDED = "superseded"
    REFUTED = "refuted"


class ReferenceMode(str, enum.Enum):
    """Which side of a cross-modal comparison is the reference (section 8).

    RNA is not truth and neither is methylation; naming the reference direction
    is what stops "concordant with RNA" from being reported as "methylation
    accuracy".
    """

    SYMMETRIC = "symmetric"
    RNA_REFERENCE = "rna_reference"
    METHYLATION_REFERENCE = "methylation_reference"


class ReferenceProvenance(str, enum.Enum):
    REVIEWED = "reviewed"
    INFERRED = "inferred"
    EXTERNAL = "external"


class ReferenceIndependence(str, enum.Enum):
    """Kept separate from provenance on purpose.

    A *reviewed* RNA label that was also used to discover the features being
    evaluated is still circular evidence. One enum cannot express both axes,
    and the case it cannot express is precisely the leakage section 8 forbids.
    """

    INDEPENDENT = "independent"
    SHARED_DERIVATION = "shared_derivation"
    CIRCULAR = "circular"


# --- serialization ----------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decode(hint: Any, value: Any, path: str) -> Any:
    """Rebuild a nested value, rejecting anything the contract does not name."""
    if hint is Any or hint is None:
        return value
    origin = typing.get_origin(hint)
    union_type = getattr(types, "UnionType", None)  # Python 3.10+ ``A | B``
    if origin is typing.Union or (union_type is not None and origin is union_type):
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if value is None and type(None) in typing.get_args(hint):
            return None
        for arg in args:
            try:
                return _decode(arg, value, path)
            except (ContractError, TypeError, ValueError):
                continue
        raise ContractError(f"{path}: no variant of {hint} accepts {value!r}")
    if origin in (list, List, Sequence):
        args = typing.get_args(hint)
        item = args[0] if args else Any
        if not isinstance(value, list):
            raise ContractError(f"{path}: expected a list, got {type(value).__name__}")
        return [_decode(item, v, f"{path}[{i}]") for i, v in enumerate(value)]
    if origin in (dict, Dict):
        args = typing.get_args(hint)
        val = args[1] if len(args) > 1 else Any
        if not isinstance(value, dict):
            raise ContractError(f"{path}: expected an object, got {type(value).__name__}")
        return {str(k): _decode(val, v, f"{path}.{k}") for k, v in value.items()}
    if origin in (tuple, Tuple):
        args = typing.get_args(hint)
        item = args[0] if args else Any
        if not isinstance(value, (list, tuple)):
            raise ContractError(f"{path}: expected a sequence, got {type(value).__name__}")
        return tuple(_decode(item, v, f"{path}[{i}]") for i, v in enumerate(value))
    if isinstance(hint, type) and issubclass(hint, enum.Enum):
        try:
            return hint(value)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in hint)
            raise ContractError(f"{path}: {value!r} is not one of {allowed}") from exc
    if dataclasses.is_dataclass(hint) and isinstance(hint, type):
        return from_dict(hint, value, path=path)
    if not isinstance(value, hint):
        raise ContractError(f"{path}: expected {getattr(hint, '__name__', hint)}, got {type(value).__name__}")
    return value


def to_dict(obj: Any) -> Any:
    """Serialize a contract object, stamping the schema version on the envelope."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        payload: Dict[str, Any] = {"schema_version": obj.SCHEMA}
        for field in dataclasses.fields(obj):
            payload[field.name] = to_dict(getattr(obj, field.name))
        return payload
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    return obj


def from_dict(cls: type, payload: Any, path: str = "") -> Any:
    """Rebuild a contract object, rejecting unknown keys and wrong schema versions."""
    label = path or cls.__name__
    if not isinstance(payload, dict):
        raise ContractError(f"{label}: expected an object, got {type(payload).__name__}")
    version = payload.get("schema_version")
    if version is None:
        raise ContractError(f"{label}: missing schema_version")
    if int(version) != cls.SCHEMA:
        raise ContractError(
            f"{label}: schema_version {version} cannot be read as version {cls.SCHEMA}"
        )
    known = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(payload) - known - {"schema_version"})
    if unknown:
        raise ContractError(f"{label}: unknown field(s) {', '.join(unknown)}")
    missing = sorted(known - set(payload))
    if missing:
        raise ContractError(f"{label}: missing field(s) {', '.join(missing)}")
    hints = typing.get_type_hints(cls)
    kwargs = {
        f.name: _decode(hints[f.name], payload[f.name], f"{label}.{f.name}")
        for f in dataclasses.fields(cls)
    }
    return cls(**kwargs)


@dataclasses.dataclass
class Contract:
    """Base for every versioned object: JSON round-trip plus a validation hook."""

    SCHEMA = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return to_dict(self)

    def validate(self) -> None:
        """Check invariants that field types alone cannot express."""

    @classmethod
    def from_dict(cls, payload: Any) -> Any:
        obj = from_dict(cls, payload)
        obj.validate()
        return obj


# --- the objects ------------------------------------------------------------


@dataclasses.dataclass
class SessionSpec(Contract):
    """Frozen at session start: scope, budget, and protocol (section 5)."""

    session_id: str
    input_signature: str
    goal: str
    routes: List[str]
    search_space: Dict[str, Any]
    evaluation_protocol: Dict[str, Any]
    review_policy: Dict[str, Any]
    budget: Dict[str, Any]
    created_at: str = dataclasses.field(default_factory=utc_now)


@dataclasses.dataclass
class ToolSpec(Contract):
    """A registered scientific tool. Models pick from these; they never supply code."""

    tool_id: str
    version: str
    modality: str
    inputs: List[str]
    outputs: List[str]
    parameters: Dict[str, Any]
    executor: str
    resources: Dict[str, Any]
    preconditions: List[str] = dataclasses.field(default_factory=list)
    postconditions: List[str] = dataclasses.field(default_factory=list)
    stochastic: bool = False
    side_effects: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class CandidateSpec(Contract):
    id: str
    route: str
    parameters: Dict[str, Any]
    estimated_cost: Dict[str, Any]
    parent: Optional[str] = None
    parameter_diff: Dict[str, Any] = dataclasses.field(default_factory=dict)
    hypothesis: str = ""


@dataclasses.dataclass
class RoundPlan(Contract):
    """A frozen round: what runs, in what order, under what reservation."""

    round_id: str
    session_id: str
    candidates: List[str]
    dag: Dict[str, Any]
    tool_versions: Dict[str, str]
    resource_envelope: Dict[str, Any]
    budget_reservation: Dict[str, Any]
    plan_digest: str
    signature: str


@dataclasses.dataclass
class ArtifactManifest(Contract):
    artifact_id: str
    kind: str
    checksum: str
    produced_by: str
    upstream: List[str] = dataclasses.field(default_factory=list)
    cell_signature: str = ""
    feature_signature: str = ""
    effective_parameters_digest: str = ""
    tool_implementation_digest: str = ""
    environment_fingerprint: str = ""
    seed: Optional[int] = None
    registry_version: str = ""
    contract_schema_version: int = SCHEMA_VERSION
    cache_key: str = ""


@dataclasses.dataclass
class EvaluationRecord(Contract):
    """One metric on one candidate. The reference fields are not decoration.

    `comparison_protocol` names the protocol this number was produced under; two
    records may only be ranked together when their protocols are compatible.
    """

    metric: str
    direction: str
    status: MetricStatus
    value: Optional[float] = None
    evaluation_set: str = ""
    fidelity: str = ""
    comparison_protocol: str = ""
    repeats: int = 1
    uncertainty: Optional[float] = None
    evidence_refs: List[str] = dataclasses.field(default_factory=list)
    reference_mode: Optional[ReferenceMode] = None
    reference_provenance: Optional[ReferenceProvenance] = None
    reference_independence: Optional[ReferenceIndependence] = None

    def validate(self) -> None:
        if self.direction not in ("maximize", "minimize", "none"):
            raise ContractError(f"EvaluationRecord.direction: {self.direction!r} is not maxim|minimize|none")
        if self.status is MetricStatus.OK and self.value is None:
            raise ContractError("EvaluationRecord: status ok requires a value")
        if self.status is not MetricStatus.OK and self.value is not None:
            raise ContractError(f"EvaluationRecord: status {self.status.value} must not carry a value")
        cross_modal = any(
            v is not None
            for v in (self.reference_mode, self.reference_provenance, self.reference_independence)
        )
        if cross_modal and None in (self.reference_mode, self.reference_provenance, self.reference_independence):
            raise ContractError(
                "EvaluationRecord: cross-modal metrics must declare reference_mode, "
                "reference_provenance and reference_independence together"
            )


@dataclasses.dataclass
class DecisionRecord(Contract):
    action: str
    rationale: str
    evidence: List[str]
    rule_or_model_version: str
    alternatives: List[str] = dataclasses.field(default_factory=list)
    budget_delta: Dict[str, Any] = dataclasses.field(default_factory=dict)
    decided_at: str = dataclasses.field(default_factory=utc_now)


@dataclasses.dataclass
class ReviewRecord(Contract):
    subject_signature: str
    reviewer: str
    conclusion: str
    evidence: List[str]
    reviewed_at: str = dataclasses.field(default_factory=utc_now)


@dataclasses.dataclass
class AnalysisStep(Contract):
    """What actually ran: parameters, environment, seeds, inputs, outputs."""

    tool_id: str
    parameters: Dict[str, Any]
    environment: str
    inputs: List[str]
    outputs: List[str]
    execution_identity: str
    seed: Optional[int] = None


@dataclasses.dataclass
class BudgetLedger(Contract):
    """Reserved and observed are separate facts and stay separate (section 10)."""

    session_id: str
    consumed: Dict[str, float] = dataclasses.field(default_factory=dict)
    reserved: Dict[str, float] = dataclasses.field(default_factory=dict)
    remaining: Dict[str, float] = dataclasses.field(default_factory=dict)
    estimated: Dict[str, float] = dataclasses.field(default_factory=dict)
    observed: Dict[str, float] = dataclasses.field(default_factory=dict)
    changes: List[Dict[str, Any]] = dataclasses.field(default_factory=list)

    def validate(self) -> None:
        for name, value in self.reserved.items():
            if value < 0:
                raise ContractError(f"BudgetLedger: reserved {name} is negative")
        for name, value in self.consumed.items():
            if value < 0:
                raise ContractError(f"BudgetLedger: consumed {name} is negative")


@dataclasses.dataclass
class MemoryObservation(Contract):
    """Evidence with a stated scope, not a permanent constraint (section 9.3).

    An observation without a scope silently becomes a superstition: it keeps
    suppressing a parameter region after the representation that made it true
    has changed. `invalidated_by` is derived from the dependency registry, not
    maintained by hand.
    """

    observation: str
    scope_signature: Dict[str, str]
    status: ObservationStatus = ObservationStatus.ACTIVE
    support: List[str] = dataclasses.field(default_factory=list)
    contradict: List[str] = dataclasses.field(default_factory=list)
    evidence_count: int = 0
    contradiction_count: int = 0
    valid_from: str = dataclasses.field(default_factory=utc_now)
    invalidated_by: List[str] = dataclasses.field(default_factory=list)

    def validate(self) -> None:
        if self.evidence_count < 0 or self.contradiction_count < 0:
            raise ContractError("MemoryObservation: evidence counts must be non-negative")
        if self.evidence_count != len(self.support):
            raise ContractError("MemoryObservation: evidence_count must match support entries")
        if self.contradiction_count != len(self.contradict):
            raise ContractError("MemoryObservation: contradiction_count must match contradict entries")
        if self.status is ObservationStatus.ACTIVE and self.invalidated_by:
            raise ContractError("MemoryObservation: an active observation cannot already be invalidated")


@dataclasses.dataclass
class ComparisonProtocol(Contract):
    """Admission to a shared Pareto front, not merely a label.

    Two candidates carrying the same metric name are not thereby comparable: a
    silhouette computed on a different cell set is a different quantity. Ranking
    across incompatible protocols is the failure this object exists to prevent.
    """

    protocol_id: str
    metrics: Dict[str, str]
    cell_set: str
    feature_set: str
    fidelity: str
    sampling: str = ""
    random_seeds: List[int] = dataclasses.field(default_factory=list)
    software_versions: Dict[str, str] = dataclasses.field(default_factory=dict)
    tolerances: Dict[str, float] = dataclasses.field(default_factory=dict)

    def validate(self) -> None:
        if not self.metrics:
            raise ContractError("ComparisonProtocol: metrics must not be empty")
        for metric, direction in self.metrics.items():
            if direction not in ("maximize", "minimize"):
                raise ContractError(
                    f"ComparisonProtocol.metrics[{metric}]: {direction!r} is not maximize|minimize"
                )

    def compatible_with(self, other: "ComparisonProtocol") -> Tuple[bool, List[str]]:
        """Whether two candidates may share a front, with the reasons they may not.

        Seeds and software versions are reported but not required to match: a
        fidelity difference is expected across rungs, and forcing identical seeds
        would forbid the repetition that makes stability measurable. Cell set,
        feature set, fidelity and metric directions define comparability.
        """
        reasons: List[str] = []
        if self.cell_set != other.cell_set:
            reasons.append(f"cell_set differs: {self.cell_set!r} vs {other.cell_set!r}")
        if self.feature_set != other.feature_set:
            reasons.append(f"feature_set differs: {self.feature_set!r} vs {other.feature_set!r}")
        if self.fidelity != other.fidelity:
            reasons.append(f"fidelity differs: {self.fidelity!r} vs {other.fidelity!r}")
        for metric in sorted(set(self.metrics) & set(other.metrics)):
            if self.metrics[metric] != other.metrics[metric]:
                reasons.append(
                    f"direction of {metric} differs: {self.metrics[metric]} vs {other.metrics[metric]}"
                )
        return (not reasons), reasons


@dataclasses.dataclass
class ConstraintSpec(Contract):
    """One gate in the funnel. Not a Pareto dimension: violating it removes the candidate."""

    constraint_id: str
    metric: str
    operator: str
    severity: ConstraintSeverity
    scope: str = ""
    threshold: Optional[float] = None
    reference: Optional[str] = None
    action: str = ""

    def validate(self) -> None:
        if self.operator not in ("<", "<=", ">", ">=", "==", "!="):
            raise ContractError(f"ConstraintSpec.operator: {self.operator!r} is not a comparison")
        if self.threshold is None and self.reference is None:
            raise ContractError(
                f"ConstraintSpec[{self.constraint_id}]: needs a threshold or a reference baseline"
            )
        if self.threshold is not None and self.reference is not None:
            raise ContractError(
                f"ConstraintSpec[{self.constraint_id}]: threshold and reference are alternatives, not both"
            )

    def qualifying_state(self) -> ScientificState:
        """The state a violation of this constraint produces (section 5)."""
        if self.severity is ConstraintSeverity.INTEGRITY:
            return ScientificState.INVALID
        if self.severity is ConstraintSeverity.PROTECTED:
            return ScientificState.REVIEW_REQUIRED
        if self.severity is ConstraintSeverity.SCIENTIFIC:
            return ScientificState.CONSTRAINT_FAILED
        raise ContractError(
            "ConstraintSpec: operational failures such as exhausted budgets do not have "
            "a ScientificState; record them in SessionState"
        )


@dataclasses.dataclass
class MultiFidelitySpec(Contract):
    """A fidelity ladder, held to the monotonic nesting invariant (section 9.2).

    Epochs 50 -> 150 -> 500 is a ladder; a random 20% followed by a different
    random 50% is two unrelated experiments, and comparing ranks across them
    produces an ordering that means nothing. Levels may declare the members they
    contain so the invariant is checkable rather than merely asserted.
    """

    dimension: str
    levels: List[Dict[str, Any]]

    def validate(self) -> None:
        if len(self.levels) < 2:
            raise ContractError("MultiFidelitySpec: a ladder needs at least two levels")
        resources = [level.get("resource") for level in self.levels]
        if any(r is None for r in resources):
            raise ContractError("MultiFidelitySpec: every level needs a 'resource' value")
        # Strictly ascending, not merely monotonic. A ladder runs from the cheap
        # screen to the expensive confirmation, and the summary above depends on
        # that direction: nesting means later rungs *contain* earlier ones, and
        # "the low-fidelity screen may only filter" means the low end is first.
        # Accepting a descending ladder would leave both statements without a
        # referent, so it is rejected here rather than silently reordered.
        if not all(a < b for a, b in zip(resources, resources[1:])):
            raise ContractError(
                f"MultiFidelitySpec: resource must increase across levels, got {resources}"
            )

    def validate_membership(self) -> List[str]:
        """Check nesting where levels declare members; report where they do not.

        A resource dimension such as epochs nests by construction, so declaring
        members there would be redundant. Returning the unchecked level names
        keeps that an explicit statement rather than an unexamined assumption.
        """
        unchecked: List[str] = []
        previous: Optional[set] = None
        for level in self.levels:
            members = level.get("members")
            if members is None:
                unchecked.append(str(level.get("name", level.get("resource"))))
                previous = None
                continue
            current = set(members)
            if previous is not None and not previous <= current:
                raise ContractError(
                    f"MultiFidelitySpec: level {level.get('name')!r} is not a superset of the "
                    f"previous level ({len(previous - current)} member(s) missing)"
                )
            previous = current
        return unchecked
