"""Fixed-panel visual evidence and deterministic checks for Scanpy review."""

from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


OBSERVATION_TYPES = (
    "sample_specific_islands",
    "disconnected_same_label",
    "bridge_patterns",
    "extreme_crowding",
    "isolated_outlier_islands",
    "possible_overfragmentation",
)

FIGURE_FILES = (
    ("cell_type_umap", "umap_candidate_cell_type.png"),
    ("leiden_umap", "umap_leiden.png"),
    ("annotation_marker_dotplot", "candidate_annotation_marker_dotplot.png"),
    ("cluster_marker_dotplot", "candidate_cluster_marker_dotplot.png"),
)


class VisualEvidenceError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png_dimensions(path: Path) -> Tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise VisualEvidenceError("visual evidence is not a valid PNG: %s" % path)
    return struct.unpack(">II", header[16:24])


def collect_visual_figures(candidate_h5ad: Path, settings: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Collect a bounded, deterministic panel from the candidate iteration."""
    figure_dir = Path(candidate_h5ad).parent / "figures"
    requested = settings.get("figure_ids") or [item[0] for item in FIGURE_FILES]
    if not isinstance(requested, list) or any(not isinstance(item, str) for item in requested):
        raise VisualEvidenceError("visual_review.figure_ids must be a list of strings")
    maximum = int(settings.get("max_images", 4))
    if maximum < 1 or maximum > 4:
        raise VisualEvidenceError("visual_review.max_images must lie in [1, 4]")
    maximum_bytes = int(settings.get("max_image_bytes", 8 * 1024 * 1024))
    known = dict(FIGURE_FILES)
    unknown = sorted(set(requested) - set(known))
    if unknown:
        raise VisualEvidenceError("unknown visual figure IDs: %s" % ", ".join(unknown))
    figures = []
    for figure_id in requested:
        path = figure_dir / known[figure_id]
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size <= 0 or size > maximum_bytes:
            raise VisualEvidenceError("visual figure size is outside its configured bound: %s" % path)
        width, height = _png_dimensions(path)
        figures.append({
            "figure_id": figure_id,
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "mime_type": "image/png",
            "bytes": int(size),
            "width": int(width),
            "height": int(height),
        })
        if len(figures) >= maximum:
            break
    return figures


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def _component_sizes(neighbors: np.ndarray, labels: Optional[np.ndarray] = None) -> List[int]:
    union = _UnionFind(len(neighbors))
    for index, row in enumerate(neighbors):
        for other in row:
            other = int(other)
            if labels is None or labels[index] == labels[other]:
                union.union(index, other)
    counts: Dict[int, int] = {}
    for index in range(len(neighbors)):
        root = union.find(index)
        counts[root] = counts.get(root, 0) + 1
    return sorted(counts.values(), reverse=True)


def _label_components(neighbors: np.ndarray, labels: np.ndarray) -> Dict[str, List[int]]:
    union = _UnionFind(len(neighbors))
    for index, row in enumerate(neighbors):
        for other in row:
            other = int(other)
            if labels[index] == labels[other]:
                union.union(index, other)
    grouped: Dict[str, Dict[int, int]] = {}
    for index, label in enumerate(labels):
        root = union.find(index)
        bucket = grouped.setdefault(str(label), {})
        bucket[root] = bucket.get(root, 0) + 1
    return {label: sorted(counts.values(), reverse=True) for label, counts in grouped.items()}


def calculate_visual_metrics(h5ad_path: Path, max_cells: int = 20000, seed: int = 0) -> Dict[str, Any]:
    """Calculate metrics that can confirm or refute bounded visual observations."""
    import anndata as ad
    from sklearn.neighbors import NearestNeighbors

    adata = ad.read_h5ad(str(h5ad_path), backed="r")
    if "X_umap_after_harmony" not in adata.obsm:
        raise VisualEvidenceError("candidate H5AD lacks X_umap_after_harmony")
    count = int(adata.n_obs)
    if count < 4:
        raise VisualEvidenceError("visual verification needs at least four cells")
    if count > max_cells:
        rng = np.random.RandomState(seed)
        selected = np.sort(rng.choice(count, max_cells, replace=False))
    else:
        selected = np.arange(count)
    values = np.asarray(adata.obsm["X_umap_after_harmony"][selected, :2], dtype=float)
    obs = adata.obs.iloc[selected]
    k = min(15, len(selected) - 1)
    distances, indices = NearestNeighbors(n_neighbors=k + 1).fit(values).kneighbors(values)
    neighbors = indices[:, 1:]
    nearest = distances[:, 1]

    sample_key = "sample" if "sample" in obs else "cohort" if "cohort" in obs else None
    sample_enrichment = None
    if sample_key:
        samples = obs[sample_key].astype(str).to_numpy()
        frequencies = {label: float(np.mean(samples == label)) for label in np.unique(samples)}
        local = np.asarray([np.mean(samples[row] == samples[index])
                            for index, row in enumerate(neighbors)], dtype=float)
        expected = np.asarray([frequencies[label] for label in samples], dtype=float)
        sample_enrichment = float(np.mean(local - expected))

    label_key = "candidate_cell_type" if "candidate_cell_type" in obs else "cell_type" if "cell_type" in obs else None
    disconnected: Dict[str, List[int]] = {}
    fragmentation: Dict[str, int] = {}
    if label_key:
        labels = obs[label_key].astype(str).to_numpy()
        raw_components = _label_components(neighbors, labels)
        for label, sizes in raw_components.items():
            minimum = max(3, int(math.ceil(sum(sizes) * 0.02)))
            meaningful = [size for size in sizes if size >= minimum]
            if len(meaningful) > 1:
                disconnected[label] = meaningful
        if "leiden" in obs:
            clusters = obs["leiden"].astype(str).to_numpy()
            for label in np.unique(labels):
                subset = clusters[labels == label]
                counts = [int(np.sum(subset == cluster)) for cluster in np.unique(subset)]
                minimum = max(3, int(math.ceil(len(subset) * 0.02)))
                fragmentation[str(label)] = sum(value >= minimum for value in counts)

    components = _component_sizes(neighbors)
    median = float(np.median(nearest))
    q01 = float(np.quantile(nearest, 0.01))
    return {
        "schema_version": 1,
        "n_cells": int(len(selected)),
        "embedding": "X_umap_after_harmony",
        "k": int(k),
        "sample_key": sample_key,
        "same_sample_neighbor_enrichment": sample_enrichment,
        "label_key": label_key,
        "disconnected_label_components": disconnected,
        "clusters_per_celltype": fragmentation,
        "max_clusters_per_celltype": max(fragmentation.values()) if fragmentation else None,
        "umap_component_sizes": components,
        "n_umap_components": len(components),
        "smallest_component_fraction": float(min(components) / len(selected)),
        "nearest_distance_median": median,
        "nearest_distance_q01": q01,
        "nearest_q01_to_median": (q01 / median if median > 0 else None),
        "duplicate_coordinate_fraction": float(np.mean(nearest <= 1e-12)),
        "seed": int(seed),
    }


def validate_observations(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise VisualEvidenceError("visual observations must be a list")
    result = []
    seen = set()
    allowed = {"observation_type", "present", "confidence", "figure_ids", "labels", "description"}
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != allowed:
            raise VisualEvidenceError("visual observation %d has an invalid schema" % index)
        kind = str(item["observation_type"])
        if kind not in OBSERVATION_TYPES:
            raise VisualEvidenceError("unknown visual observation type: %s" % kind)
        if kind in seen:
            raise VisualEvidenceError("duplicate visual observation type: %s" % kind)
        seen.add(kind)
        if not isinstance(item["present"], bool):
            raise VisualEvidenceError("visual observation present must be boolean")
        confidence = float(item["confidence"])
        if not 0 <= confidence <= 1:
            raise VisualEvidenceError("visual observation confidence must lie in [0, 1]")
        figures = item["figure_ids"]
        labels = item["labels"]
        description = str(item["description"]).strip()
        if (not isinstance(figures, list) or not figures or not all(isinstance(x, str) and x for x in figures)
                or not isinstance(labels, list) or not all(isinstance(x, str) for x in labels)
                or not description or len(description) > 1000):
            raise VisualEvidenceError("visual observation %d has invalid evidence text or lists" % index)
        result.append({"observation_type": kind, "present": item["present"],
                       "confidence": confidence, "figure_ids": figures,
                       "labels": labels, "description": description})
    return result


def verify_observations(observations: Sequence[Mapping[str, Any]], metrics: Mapping[str, Any],
                        thresholds: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    thresholds = thresholds or {}
    sample_cutoff = float(thresholds.get("sample_enrichment", 0.25))
    crowding_cutoff = float(thresholds.get("crowding_q01_ratio", 0.05))
    duplicate_cutoff = float(thresholds.get("duplicate_fraction", 0.005))
    fragmentation_cutoff = int(thresholds.get("clusters_per_celltype", 2))
    results = []
    for observation in observations:
        kind = str(observation["observation_type"])
        labels = list(observation.get("labels") or [])
        detected: Optional[bool]
        evidence: Dict[str, Any]
        if kind == "sample_specific_islands":
            value = metrics.get("same_sample_neighbor_enrichment")
            detected = None if value is None else float(value) >= sample_cutoff
            evidence = {"same_sample_neighbor_enrichment": value, "threshold": sample_cutoff}
        elif kind == "disconnected_same_label":
            values = metrics.get("disconnected_label_components") or {}
            selected = {key: values[key] for key in labels if key in values} if labels else values
            detected = bool(selected)
            evidence = {"disconnected_label_components": selected}
        elif kind == "extreme_crowding":
            ratio = metrics.get("nearest_q01_to_median")
            duplicate = metrics.get("duplicate_coordinate_fraction")
            detected = None if ratio is None or duplicate is None else (
                float(ratio) <= crowding_cutoff or float(duplicate) >= duplicate_cutoff)
            evidence = {"nearest_q01_to_median": ratio, "ratio_threshold": crowding_cutoff,
                        "duplicate_coordinate_fraction": duplicate,
                        "duplicate_threshold": duplicate_cutoff}
        elif kind == "isolated_outlier_islands":
            components = int(metrics.get("n_umap_components", 0))
            fraction = metrics.get("smallest_component_fraction")
            detected = components > 1 and fraction is not None and float(fraction) <= 0.10
            evidence = {"n_umap_components": components, "smallest_component_fraction": fraction}
        elif kind == "possible_overfragmentation":
            values = metrics.get("clusters_per_celltype") or {}
            selected = {key: values[key] for key in labels if key in values} if labels else values
            detected = any(int(value) >= fragmentation_cutoff for value in selected.values())
            evidence = {"clusters_per_celltype": selected, "threshold": fragmentation_cutoff}
        else:  # A robust numerical bridge detector is deliberately not invented.
            detected = None
            evidence = {"reason": "no deterministic bridge-pattern validator in V0.1"}
        if detected is None:
            verdict = "unverified"
        elif bool(observation["present"]) == detected:
            verdict = "confirmed"
        else:
            verdict = "refuted"
        results.append({"observation_type": kind, "visual_present": bool(observation["present"]),
                        "verdict": verdict, "metric_evidence": evidence})
    return results
