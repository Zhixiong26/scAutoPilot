"""Type-safe decision primitives used by rule and model policy backends.

The primitive is chosen by the caller. A backend never turns a vague prompt into
an unconstrained action: Noul is binary, Score is ordered, and Choice is limited
to caller-declared mutually exclusive actions.
"""

from __future__ import annotations

import dataclasses
from typing import Dict, List


class PrimitiveError(RuntimeError):
    pass


def _distribution(values: Dict[str, float], allowed: List[str]) -> Dict[str, float]:
    if set(values) != set(allowed):
        raise PrimitiveError("probability keys do not match the declared outcomes")
    if any(value < 0 or value > 1 for value in values.values()):
        raise PrimitiveError("probabilities must lie in [0, 1]")
    total = sum(values.values())
    if abs(total - 1.0) > 1e-6:
        raise PrimitiveError("probabilities must sum to one, got %.8f" % total)
    return {key: float(values[key]) for key in allowed}


@dataclasses.dataclass(frozen=True)
class Noul:
    question_id: str
    instructions: str
    probability_yes: float
    backend: str
    evidence: List[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        if not 0 <= self.probability_yes <= 1:
            raise PrimitiveError("Noul probability_yes must lie in [0, 1]")
        return {
            "primitive": "noul", "question_id": self.question_id,
            "instructions": self.instructions, "probability_yes": self.probability_yes,
            "probability_no": 1.0 - self.probability_yes, "backend": self.backend,
            "evidence": list(self.evidence),
        }


@dataclasses.dataclass(frozen=True)
class Score:
    question_id: str
    instructions: str
    levels: List[str]
    probabilities: Dict[str, float]
    backend: str
    evidence: List[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        if len(self.levels) < 2 or len(set(self.levels)) != len(self.levels):
            raise PrimitiveError("Score needs at least two unique ordered levels")
        probabilities = _distribution(self.probabilities, self.levels)
        expected = sum(index * probabilities[level] for index, level in enumerate(self.levels))
        return {
            "primitive": "score", "question_id": self.question_id,
            "instructions": self.instructions, "levels": list(self.levels),
            "probabilities": probabilities, "expected_score": expected,
            "backend": self.backend, "evidence": list(self.evidence),
        }


@dataclasses.dataclass(frozen=True)
class Choice:
    question_id: str
    instructions: str
    criteria: Dict[str, str]
    probabilities: Dict[str, float]
    backend: str
    evidence: List[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        if len(self.criteria) < 2:
            raise PrimitiveError("Choice needs at least two legal outcomes")
        allowed = list(self.criteria)
        probabilities = _distribution(self.probabilities, allowed)
        selected = max(allowed, key=lambda key: probabilities[key])
        return {
            "primitive": "choice", "question_id": self.question_id,
            "instructions": self.instructions, "criteria": dict(self.criteria),
            "probabilities": probabilities, "selected": selected,
            "backend": self.backend, "evidence": list(self.evidence),
        }
