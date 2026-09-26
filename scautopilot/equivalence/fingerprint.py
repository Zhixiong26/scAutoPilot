"""Artifact fingerprints and the measured noise floor (plan.md sections 13.1, 13.3).

A fingerprint is the compact, comparable summary of one artifact: small enough
to sit in the control plane, specific enough to decide whether a run reproduced
another. It is not the artifact, and it is not a quality score -- a fingerprint
says what came out, never whether it was good.

The noise floor is the part that makes the rest honest. Deciding whether a
wrapped refactor reproduced the original needs a tolerance, and a tolerance
chosen by taste is a number nobody can defend later. So the original
implementation is run more than once, unchanged, and the spread it shows on its
own becomes the yardstick it is later held to. If the original does not
reproduce itself, "exactly equivalent" is not a claim anyone can make, and the
protocols say so rather than inventing a tolerance to cover for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import compare

SCHEMA_VERSION = 1


class FingerprintError(RuntimeError):
    """A fingerprint is malformed, or two fingerprints cannot be compared."""


class ArtifactClass(str, Enum):
    """How an artifact must be compared. Chosen by the artifact, not by taste.

    The split that matters is determinism. Identity, integer and (canonicalised)
    discrete artifacts are either equal or not; wrapping them in a tolerance
    would let a refactor that *did* change behaviour pass by claiming closeness.
    Float and stochastic artifacts have a spread even when nothing changed, so
    they need the margin the noise floor measured.
    """

    IDENTITY = "identity"
    INTEGER = "integer"
    DISCRETE = "discrete"
    FLOAT = "float"
    SET = "set"
    STOCHASTIC = "stochastic"


EXACT_CLASSES = frozenset({ArtifactClass.IDENTITY, ArtifactClass.INTEGER, ArtifactClass.DISCRETE})
TOLERANT_CLASSES = frozenset({ArtifactClass.FLOAT, ArtifactClass.STOCHASTIC, ArtifactClass.SET})


@dataclass(frozen=True)
class Fingerprint:
    """One artifact's comparable summary.

    `sampling` records how cells, features or points were subsampled. Two
    fingerprints with different sampling are not comparable: the difference
    between them may be the sampling rather than the analysis.
    """

    artifact_id: str
    artifact_class: ArtifactClass
    payload: Dict[str, Any]
    sampling: str = ""
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_class, ArtifactClass):
            raise FingerprintError(
                "fingerprint %s: unknown artifact class %r" % (self.artifact_id, self.artifact_class)
            )
        has_values = "values" in self.payload or "labels" in self.payload or "members" in self.payload
        has_digest = "digest" in self.payload
        if not (has_values or has_digest):
            raise FingerprintError(
                "fingerprint %s: payload needs one of values, labels, members or digest"
                % self.artifact_id
            )
        if has_values and has_digest:
            raise FingerprintError(
                "fingerprint %s: payload carries both a digest and raw values; "
                "pick one so comparison is unambiguous" % self.artifact_id
            )
        if self.artifact_class is ArtifactClass.DISCRETE and "labels" not in self.payload:
            raise FingerprintError(
                "fingerprint %s: discrete artifacts store labels, since canonicalising "
                "a digest cannot separate a relabelling from a real change" % self.artifact_id
            )
        if self.artifact_class in EXACT_CLASSES and "values" in self.payload:
            # Floats in an exact class are how a tolerance quietly becomes a
            # pass/fail rule the plan never agreed to.
            for value in self.payload["values"]:
                if isinstance(value, float) and value != int(value):
                    raise FingerprintError(
                        "fingerprint %s: class %s must hold integers, found %r"
                        % (self.artifact_id, self.artifact_class.value, value)
                    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "artifact_class": self.artifact_class.value,
            "payload": self.payload,
            "sampling": self.sampling,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Fingerprint":
        version = payload.get("schema_version")
        if int(version or 0) != SCHEMA_VERSION:
            raise FingerprintError(
                "fingerprint %s: schema_version %s cannot be read as version %s"
                % (payload.get("artifact_id"), version, SCHEMA_VERSION)
            )
        try:
            artifact_class = ArtifactClass(payload["artifact_class"])
        except (KeyError, ValueError) as exc:
            raise FingerprintError(
                "fingerprint %s: unknown artifact_class %r"
                % (payload.get("artifact_id"), payload.get("artifact_class"))
            ) from exc
        return cls(
            artifact_id=str(payload["artifact_id"]),
            artifact_class=artifact_class,
            payload=dict(payload.get("payload") or {}),
            sampling=str(payload.get("sampling", "")),
        )

    @property
    def digest(self) -> str:
        """Canonical hash of the payload, for exact comparison of large artifacts."""
        return json.dumps(self.payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ArtifactNoise:
    """What one artifact did when nothing changed.

    `observations` is reported because the estimate's strength depends on it: a
    spread seen twice is a point estimate, not a distribution, and the derived
    tolerance is only as good as that.
    """

    artifact_id: str
    artifact_class: ArtifactClass
    observations: int
    deterministic: bool
    max_abs_delta: float = 0.0
    max_rel_delta: float = 0.0
    overlap_floor: Optional[float] = None

    def tolerance(self, safety_factor: float = 10.0) -> Tuple[float, float]:
        """Derive (rtol, atol) from the observed spread.

        The safety factor widens the measured spread, because the spread seen in
        a handful of runs is a lower bound on the spread that exists. A
        deterministic artifact gets zero tolerance: it reproduced exactly, so
        anything other than exact reproduction is a change.
        """
        if self.deterministic:
            return (0.0, 0.0)
        if self.overlap_floor is not None:
            raise FingerprintError(
                "artifact %s is set-valued; use overlap_floor, not a numeric tolerance"
                % self.artifact_id
            )
        if safety_factor <= 0:
            raise FingerprintError("safety_factor must be positive")
        return (self.max_rel_delta * safety_factor, self.max_abs_delta * safety_factor)

    def required_overlap(self) -> float:
        """The lowest set overlap the original showed against itself.

        Deterministic membership means the sets were identical every time, so
        the floor is 1.0 and the comparison is exact set equality. A floor below
        1.0 is a measured fact about the baseline: that is how much membership
        drifted when nothing changed, and a candidate is held to that, not to a
        number chosen here.
        """
        if self.overlap_floor is not None:
            return self.overlap_floor
        return 1.0 if self.deterministic else 0.0


@dataclass
class NoiseFloor:
    """The measured reproducibility of the *original* implementation.

    Everything the wrapper equivalence protocol decides is measured against
    this. It is deliberately a property of the baseline, not of the candidate:
    the question is whether the new code behaves like the old one, and the old
    one's own variability is the only fair reference.
    """

    observations: int
    artifacts: Dict[str, ArtifactNoise] = field(default_factory=dict)
    label: str = ""

    def get(self, artifact_id: str) -> ArtifactNoise:
        try:
            return self.artifacts[artifact_id]
        except KeyError as exc:
            raise FingerprintError(
                "artifact %s has no measured noise floor; run the baseline at least twice "
                "before judging equivalence" % artifact_id
            ) from exc

    def deterministic_artifacts(self) -> List[str]:
        return sorted(a for a, noise in self.artifacts.items() if noise.deterministic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "label": self.label,
            "observations": self.observations,
            "artifacts": {
                artifact_id: {
                    "artifact_class": noise.artifact_class.value,
                    "observations": noise.observations,
                    "deterministic": noise.deterministic,
                    "max_abs_delta": noise.max_abs_delta,
                    "max_rel_delta": noise.max_rel_delta,
                }
                for artifact_id, noise in self.artifacts.items()
            },
        }


def measure_noise_floor(runs: Sequence[Mapping[str, Fingerprint]], label: str = "") -> NoiseFloor:
    """Derive the noise floor from repeated runs of the unchanged implementation.

    Two runs are the minimum the protocol allows, and the result says so through
    `observations`. More is better; the number is carried forward so a tolerance
    derived from two runs is never mistaken for one derived from ten.
    """
    if len(runs) < 2:
        raise FingerprintError(
            "noise floor needs at least two runs of the unchanged implementation, got %d"
            % len(runs)
        )
    shared = set(runs[0])
    for run in runs[1:]:
        shared &= set(run)
    if not shared:
        raise FingerprintError("noise floor: the runs share no artifacts")

    artifacts: Dict[str, ArtifactNoise] = {}
    for artifact_id in sorted(shared):
        exemplar = runs[0][artifact_id]
        if exemplar.artifact_class in EXACT_CLASSES:
            same = all(
                compare.labels_identical(
                    runs[0][artifact_id].payload.get("labels", []),
                    run[artifact_id].payload.get("labels", []),
                )
                if exemplar.artifact_class is ArtifactClass.DISCRETE
                else _payloads_equal(runs[0][artifact_id], run[artifact_id])
                for run in runs[1:]
            )
            artifacts[artifact_id] = ArtifactNoise(
                artifact_id=artifact_id,
                artifact_class=exemplar.artifact_class,
                observations=len(runs),
                deterministic=same,
            )
            continue

        worst_abs = 0.0
        worst_rel = 0.0
        overlap_floor: Optional[float] = None
        if exemplar.artifact_class is ArtifactClass.SET:
            # A set is judged by membership, not by deviation. A gene set has no
            # "close", only "same members" or "these members differ"; the
            # baseline's own drift between runs becomes the floor the candidate
            # must reach, and an undrifted baseline makes that exact equality.
            overlap_floor = 1.0
            for left_index in range(len(runs)):
                for right_index in range(left_index + 1, len(runs)):
                    overlap_floor = min(
                        overlap_floor,
                        compare.jaccard(
                            _members(runs[left_index][artifact_id]),
                            _members(runs[right_index][artifact_id]),
                        ),
                    )
        else:
            for left_index in range(len(runs)):
                for right_index in range(left_index + 1, len(runs)):
                    delta_abs, delta_rel = _numeric_spread(
                        runs[left_index][artifact_id], runs[right_index][artifact_id]
                    )
                    worst_abs = max(worst_abs, delta_abs)
                    worst_rel = max(worst_rel, delta_rel)
        artifacts[artifact_id] = ArtifactNoise(
            artifact_id=artifact_id,
            artifact_class=exemplar.artifact_class,
            observations=len(runs),
            deterministic=(worst_abs == 0.0 and worst_rel == 0.0 and overlap_floor in (None, 1.0)),
            max_abs_delta=worst_abs,
            max_rel_delta=worst_rel,
            overlap_floor=overlap_floor,
        )
    return NoiseFloor(observations=len(runs), artifacts=artifacts, label=label)


def _members(fingerprint: Fingerprint) -> Sequence[object]:
    for key in ("members", "labels", "values"):
        if key in fingerprint.payload:
            raw = fingerprint.payload[key]
            if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
                return [tuple(row) for row in raw]
            return list(raw)
    return []


def _payloads_equal(left: Fingerprint, right: Fingerprint) -> bool:
    if "digest" in left.payload or "digest" in right.payload:
        return left.payload.get("digest") == right.payload.get("digest")
    return left.digest == right.digest


def _numeric_spread(left: Fingerprint, right: Fingerprint) -> Tuple[float, float]:
    """Max absolute and relative deviation between two numeric fingerprints."""
    if "digest" in left.payload or "digest" in right.payload:
        if left.payload.get("digest") == right.payload.get("digest"):
            return (0.0, 0.0)
        raise FingerprintError(
            "fingerprint %s: digests differ, so no deviation can be measured. "
            "A digest proves inequality but cannot size it; store values if the "
            "magnitude has to be reported." % left.artifact_id
        )
    left_values = _numeric_values(left)
    right_values = _numeric_values(right)
    if len(left_values) != len(right_values):
        raise FingerprintError(
            "fingerprint %s: implementations produced %d and %d values"
            % (left.artifact_id, len(left_values), len(right_values))
        )
    _, worst_abs, worst_rel = compare.allclose(left_values, right_values, rtol=0.0, atol=0.0)
    return (worst_abs, worst_rel)


def _numeric_values(fingerprint: Fingerprint) -> List[float]:
    for key in ("values", "labels", "members"):
        if key in fingerprint.payload:
            raw = fingerprint.payload[key]
            if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
                return [float(v) for row in raw for v in row]
            return [float(v) for v in raw]
    raise FingerprintError("fingerprint %s carries no numeric values" % fingerprint.artifact_id)
