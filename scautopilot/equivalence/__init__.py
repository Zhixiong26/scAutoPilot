"""Fingerprints, the measured noise floor, and the two adjudication protocols.

Wrapper equivalence and scientific stability live side by side here so that the
temptation to reuse one for the other is visible rather than convenient; see
`protocols` for why they must not be merged.
"""

from __future__ import annotations

from .fingerprint import (
    ArtifactClass,
    ArtifactNoise,
    Fingerprint,
    FingerprintError,
    NoiseFloor,
    measure_noise_floor,
)
from .protocols import (
    ArtifactVerdict,
    EquivalenceReport,
    ProtocolError,
    ScientificStability,
    StabilityCriteria,
    StabilityVerdict,
    Verdict,
    WrapperEquivalence,
    rank_reversal_pairs,
)

__all__ = [
    "ArtifactClass",
    "ArtifactNoise",
    "ArtifactVerdict",
    "EquivalenceReport",
    "Fingerprint",
    "FingerprintError",
    "NoiseFloor",
    "ProtocolError",
    "ScientificStability",
    "StabilityCriteria",
    "StabilityVerdict",
    "Verdict",
    "WrapperEquivalence",
    "measure_noise_floor",
    "rank_reversal_pairs",
]
