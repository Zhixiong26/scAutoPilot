"""The two adjudication protocols (plan.md sections 13.1 and 13.2).

They are separate because they answer different questions, and the plan treats
merging them as the single easiest way to get a refactor signed off that did
change behaviour:

* **Wrapper equivalence** asks "is this the same implementation?" It is the M2
  gate. It uses exact comparison wherever the baseline is deterministic, and the
  baseline's own measured spread where it is not.
* **Scientific stability** asks "are these two candidates alike enough?" It
  feeds the stability evidence of section 7.1 and the promotion decisions of
  section 9.2. It uses similarity measures, which are the right tool here and
  the wrong tool there.

The classes below share no threshold table, no defaults, and no base class, and
`WrapperEquivalence` refuses to be constructed with a stability table. That
refusal is the point: an ARI of 0.99 still means some cells moved, so a
similarity threshold can never establish that nothing changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import compare
from .fingerprint import (
    TOLERANT_CLASSES,
    ArtifactClass,
    Fingerprint,
    FingerprintError,
    NoiseFloor,
)

DEFAULT_SAFETY_FACTOR = 10.0


class Verdict(str, Enum):
    EQUIVALENT = "equivalent"
    DIFFERED = "differed"
    NOT_COMPARABLE = "not_comparable"


class ProtocolError(RuntimeError):
    """A protocol was asked to do something its own rules forbid."""


@dataclass(frozen=True)
class ArtifactVerdict:
    artifact_id: str
    verdict: Verdict
    detail: str
    observed: Dict[str, float] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.verdict is not Verdict.EQUIVALENT


@dataclass
class EquivalenceReport:
    """The M2 gate's answer, per artifact and overall.

    The overall verdict is the worst artifact verdict. A wrapper that reproduced
    nineteen artifacts and changed the twentieth has changed behaviour, and
    averaging would hide exactly the case the gate exists to catch.
    """

    verdict: Verdict
    artifacts: Tuple[ArtifactVerdict, ...]
    label: str = ""

    @property
    def blockers(self) -> List[ArtifactVerdict]:
        return [v for v in self.artifacts if v.blocking]

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.EQUIVALENT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "verdict": self.verdict.value,
            "passed": self.passed,
            "artifacts": [
                {
                    "artifact_id": v.artifact_id,
                    "verdict": v.verdict.value,
                    "detail": v.detail,
                    "observed": v.observed,
                }
                for v in self.artifacts
            ],
        }


class WrapperEquivalence:
    """M0/M2 regression gate: did wrapping change what the code computes?

    Deliberately takes a `NoiseFloor` and nothing else. There is no threshold
    parameter to set, because every tolerance in play was measured from the
    original implementation rather than chosen by whoever wanted the gate to
    pass.
    """

    def __init__(self, noise_floor: NoiseFloor, safety_factor: float = DEFAULT_SAFETY_FACTOR):
        if not isinstance(noise_floor, NoiseFloor):
            raise ProtocolError(
                "WrapperEquivalence takes a measured NoiseFloor. A stability criteria "
                "table is not a substitute: similarity thresholds permit change, and "
                "this gate exists to detect change."
            )
        self.noise_floor = noise_floor
        self.safety_factor = safety_factor

    def compare(
        self,
        baseline: Mapping[str, Fingerprint],
        candidate: Mapping[str, Fingerprint],
    ) -> EquivalenceReport:
        verdicts: List[ArtifactVerdict] = []
        for artifact_id in sorted(set(baseline) | set(candidate)):
            left, right = baseline.get(artifact_id), candidate.get(artifact_id)
            if left is None or right is None:
                missing = "baseline" if left is None else "candidate"
                verdicts.append(
                    ArtifactVerdict(
                        artifact_id,
                        Verdict.NOT_COMPARABLE,
                        "produced by only one side: missing from %s" % missing,
                    )
                )
                continue
            verdicts.append(self._compare_one(left, right))
        return EquivalenceReport(
            verdict=_worst(v.verdict for v in verdicts),
            artifacts=tuple(verdicts),
            label=self.noise_floor.label,
        )

    def _compare_one(self, left: Fingerprint, right: Fingerprint) -> ArtifactVerdict:
        if left.artifact_class is not right.artifact_class:
            return ArtifactVerdict(
                left.artifact_id,
                Verdict.NOT_COMPARABLE,
                "artifact class changed: %s -> %s"
                % (left.artifact_class.value, right.artifact_class.value),
            )
        if left.sampling != right.sampling:
            return ArtifactVerdict(
                left.artifact_id,
                Verdict.NOT_COMPARABLE,
                "sampling changed (%r -> %r); the difference may be the sampling"
                % (left.sampling, right.sampling),
            )
        try:
            noise = self.noise_floor.get(left.artifact_id)
        except FingerprintError as exc:
            return ArtifactVerdict(left.artifact_id, Verdict.NOT_COMPARABLE, str(exc))

        if left.artifact_class is ArtifactClass.DISCRETE:
            same = compare.labels_identical(
                left.payload.get("labels", []), right.payload.get("labels", [])
            )
            return ArtifactVerdict(
                left.artifact_id,
                Verdict.EQUIVALENT if same else Verdict.DIFFERED,
                "canonical label sequences match" if same else "partitions differ after canonicalisation",
            )

        if left.artifact_class is ArtifactClass.IDENTITY or left.artifact_class is ArtifactClass.INTEGER:
            same = _payload_equal(left, right)
            return ArtifactVerdict(
                left.artifact_id,
                Verdict.EQUIVALENT if same else Verdict.DIFFERED,
                "exact match" if same else "exact classes must match exactly",
            )

        if left.artifact_class is ArtifactClass.SET or noise.overlap_floor is not None:
            overlap = compare.jaccard(_members(left), _members(right))
            required = noise.required_overlap()
            ok = overlap >= required
            return ArtifactVerdict(
                left.artifact_id,
                Verdict.EQUIVALENT if ok else Verdict.DIFFERED,
                "set overlap %.6f vs required %.6f" % (overlap, required),
                {"overlap": overlap, "required": required},
            )

        # Float and stochastic artifacts: the noise floor measured while nothing
        # changed is the only tolerance this comparison is allowed to use.
        try:
            left_values, right_values = _values(left), _values(right)
        except FingerprintError as exc:
            return ArtifactVerdict(left.artifact_id, Verdict.NOT_COMPARABLE, str(exc))
        rtol, atol = noise.tolerance(self.safety_factor)
        ok, worst_abs, worst_rel = compare.allclose(left_values, right_values, rtol=rtol, atol=atol)
        detail = (
            "deterministic baseline; exact reproduction required"
            if noise.deterministic
            else "within measured noise floor (rtol %.3g, atol %.3g)"
            % (rtol, atol)
        )
        return ArtifactVerdict(
            left.artifact_id,
            Verdict.EQUIVALENT if ok else Verdict.DIFFERED,
            detail,
            {"max_abs_delta": worst_abs, "max_rel_delta": worst_rel, "rtol": rtol, "atol": atol},
        )


@dataclass(frozen=True)
class StabilityCriteria:
    """Thresholds for judging whether two candidates resemble each other.

    These are similarity floors, and they are *not* equivalence criteria. They
    belong to promotion and stability evidence -- never to the M2 gate.
    """

    ari: float = 0.90
    jaccard: float = 0.80
    spearman: float = 0.90
    distance_correlation: float = 0.95
    edge_overlap: float = 0.80

    def threshold(self, metric: str) -> float:
        try:
            return float(getattr(self, metric))
        except AttributeError as exc:
            raise ProtocolError("unknown stability metric: %s" % metric) from exc


STABILITY_METRICS = ("ari", "jaccard", "spearman", "distance_correlation", "edge_overlap")


@dataclass(frozen=True)
class StabilityVerdict:
    metric: str
    value: float
    threshold: float

    @property
    def stable(self) -> bool:
        return self.value >= self.threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "stable": self.stable,
        }


class ScientificStability:
    """Stability and multi-fidelity judgements (sections 7.1, 9.2).

    Refuses a `NoiseFloor`, for the same reason the equivalence gate refuses
    this class's criteria: the two answer different questions and the plan keeps
    their thresholds independent on purpose.
    """

    def __init__(self, criteria: StabilityCriteria):
        if isinstance(criteria, NoiseFloor):
            raise ProtocolError(
                "ScientificStability takes StabilityCriteria. A measured noise floor "
                "establishes equivalence, not resemblance; using it here would decide "
                "whether two candidates are alike from whether one reproduced itself."
            )
        self.criteria = criteria

    def evaluate(self, metric: str, left: Fingerprint, right: Fingerprint) -> StabilityVerdict:
        value = self.measure(metric, left, right)
        return StabilityVerdict(metric=metric, value=value, threshold=self.criteria.threshold(metric))

    def measure(self, metric: str, left: Fingerprint, right: Fingerprint) -> float:
        if left.sampling != right.sampling:
            raise ProtocolError(
                "cannot compare %s across different sampling (%r vs %r)"
                % (left.artifact_id, left.sampling, right.sampling)
            )
        if metric == "ari":
            return compare.adjusted_rand_index(
                left.payload.get("labels", []), right.payload.get("labels", [])
            )
        if metric == "jaccard":
            return compare.jaccard(_members(left), _members(right))
        if metric == "spearman":
            left_values, right_values = _values(left), _values(right)
            if len(left_values) != len(right_values):
                raise ProtocolError(
                    "spearman needs equal-length vectors for %s (%d vs %d)"
                    % (left.artifact_id, len(left_values), len(right_values))
                )
            return compare.spearman(left_values, right_values)
        if metric == "distance_correlation":
            return compare.pairwise_distance_correlation(_points(left), _points(right))
        if metric == "edge_overlap":
            return compare.edge_overlap(_edges(left), _edges(right))
        raise ProtocolError(
            "unknown stability metric %r; expected one of %s" % (metric, ", ".join(STABILITY_METRICS))
        )


def rank_reversal_pairs(
    low_fidelity: Mapping[str, float],
    high_fidelity: Mapping[str, float],
    tolerance: float = 0.0,
) -> List[Tuple[str, str]]:
    """Candidate pairs whose ordering disagrees between two fidelity rungs.

    Section 9.2 keeps an exploration quota to notice exactly this. A reversal is
    not proof that the low-fidelity screen is worthless, but repeated reversals
    are evidence that eliminating on it is unsafe, and the pairs are returned so
    the decision cites the specific candidates rather than a count.
    """
    shared = sorted(set(low_fidelity) & set(high_fidelity))
    reversals: List[Tuple[str, str]] = []
    for index, first in enumerate(shared):
        for second in shared[index + 1:]:
            low_delta = low_fidelity[first] - low_fidelity[second]
            high_delta = high_fidelity[first] - high_fidelity[second]
            if abs(low_delta) <= tolerance or abs(high_delta) <= tolerance:
                continue
            if (low_delta > 0) != (high_delta > 0):
                reversals.append((first, second))
    return reversals


def _worst(verdicts) -> Verdict:
    ranked = [Verdict.EQUIVALENT, Verdict.DIFFERED, Verdict.NOT_COMPARABLE]
    worst = Verdict.EQUIVALENT
    for verdict in verdicts:
        if ranked.index(verdict) > ranked.index(worst):
            worst = verdict
    return worst


def _payload_equal(left: Fingerprint, right: Fingerprint) -> bool:
    if "digest" in left.payload or "digest" in right.payload:
        return left.payload.get("digest") == right.payload.get("digest")
    return left.digest == right.digest


def _values(fingerprint: Fingerprint) -> List[float]:
    for key in ("values", "labels"):
        if key in fingerprint.payload:
            raw = fingerprint.payload[key]
            if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
                return [float(v) for row in raw for v in row]
            return [float(v) for v in raw]
    raise FingerprintError("fingerprint %s carries no numeric values" % fingerprint.artifact_id)


def _members(fingerprint: Fingerprint) -> List[Any]:
    for key in ("members", "labels", "values"):
        if key in fingerprint.payload:
            raw = fingerprint.payload[key]
            if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
                return [tuple(row) for row in raw]
            return list(raw)
    return []


def _points(fingerprint: Fingerprint) -> List[List[float]]:
    raw = fingerprint.payload.get("points")
    if raw is None:
        raise FingerprintError(
            "fingerprint %s has no 'points' for a geometric comparison" % fingerprint.artifact_id
        )
    return [[float(v) for v in point] for point in raw]


def _edges(fingerprint: Fingerprint) -> List[Tuple[str, str]]:
    raw = fingerprint.payload.get("edges")
    if raw is None:
        raise FingerprintError(
            "fingerprint %s has no 'edges' for a graph comparison" % fingerprint.artifact_id
        )
    return [(str(pair[0]), str(pair[1])) for pair in raw]
