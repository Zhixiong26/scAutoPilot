"""Constrained scientific optimization control plane for single-cell multiomics.

Six engines -- Planning, Execution, Evidence, Optimization, Provenance, Review --
are responsibility boundaries inside this package, not services and not six
conversational agents (plan.md section 3).

This package holds light control logic only. Scientific dependencies stay in the
per-stage analysis environments; nothing here imports scanpy, anndata, or scipy.
The equivalence comparisons in `scautopilot.equivalence` are written so the
control plane can adjudicate fingerprints extracted on a compute node without
having that node's stack installed locally.
"""

from __future__ import annotations

__all__ = ["contracts", "equivalence", "provenance"]

VERSION = "0.1.0"
