"""Objective Scanpy/UMAP MVP benchmarks used to build the Jev state."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np


def _safe_metric(function, *args, **kwargs) -> Optional[float]:
    try:
        value = float(function(*args, **kwargs))
    except (ValueError, TypeError, FloatingPointError):
        return None
    return value if np.isfinite(value) else None


def _knn_indices(values: np.ndarray, k: int) -> np.ndarray:
    from sklearn.neighbors import NearestNeighbors

    count = min(k + 1, values.shape[0])
    model = NearestNeighbors(n_neighbors=count).fit(values)
    # Pass the training matrix explicitly.  With X=None sklearn adds one to the
    # requested neighbor count in order to remove self, which fails at k=n-1.
    indices = model.kneighbors(values, return_distance=False)
    return np.asarray([[item for item in row if item != index][:k]
                       for index, row in enumerate(indices)], dtype=int)


def knn_preservation(reference: np.ndarray, embedding: np.ndarray, k: int) -> float:
    high, low = _knn_indices(reference, k), _knn_indices(embedding, k)
    return float(np.mean([len(set(a) & set(b)) / k for a, b in zip(high, low)]))


def normalized_ilisi(values: np.ndarray, batches: np.ndarray, k: int) -> Optional[float]:
    unique = np.unique(batches)
    if unique.size < 2:
        return None
    neighbors = _knn_indices(values, k)
    scores = []
    for row in neighbors:
        _, counts = np.unique(batches[row], return_counts=True)
        probabilities = counts / counts.sum()
        scores.append(1.0 / np.square(probabilities).sum())
    raw = float(np.mean(scores))
    return float(np.clip((raw - 1.0) / (unique.size - 1.0), 0.0, 1.0))


def calculate_scanpy_benchmarks(h5ad_path, parameters: Dict[str, Any], max_cells: int = 20000) -> Dict[str, Any]:
    import anndata as ad
    from sklearn.manifold import trustworthiness
    from sklearn.metrics import davies_bouldin_score, silhouette_score

    adata = ad.read_h5ad(str(h5ad_path), backed="r")
    required = {"X_pca_harmony", "X_umap_after_harmony"}
    missing = sorted(required - set(adata.obsm.keys()))
    if missing:
        raise ValueError("candidate H5AD lacks representation(s): %s" % ", ".join(missing))
    count = adata.n_obs
    if count < 4:
        raise ValueError("benchmark needs at least four cells")
    if count > max_cells:
        rng = np.random.RandomState(0)
        selected = np.sort(rng.choice(count, max_cells, replace=False))
    else:
        selected = np.arange(count)
    n_pcs = min(int(parameters["n_pcs"]), adata.obsm["X_pca_harmony"].shape[1])
    high = np.asarray(adata.obsm["X_pca_harmony"][selected, :n_pcs])
    low = np.asarray(adata.obsm["X_umap_after_harmony"][selected, :])
    obs = adata.obs.iloc[selected]
    k = min(int(parameters["n_neighbors"]), len(selected) - 1)
    leiden = obs["leiden"].astype(str).to_numpy()
    cell_type_key = "candidate_cell_type" if "candidate_cell_type" in obs else "cell_type"
    cell_types = obs[cell_type_key].astype(str).to_numpy() if cell_type_key in obs else None
    batch_key = "sample" if "sample" in obs else "cohort" if "cohort" in obs else None
    batches = obs[batch_key].astype(str).to_numpy() if batch_key else None

    embedding = {
        "trustworthiness": _safe_metric(trustworthiness, high, low, n_neighbors=k),
        "knn_preservation": _safe_metric(knn_preservation, high, low, k),
    }
    clustering = {
        "silhouette": (_safe_metric(silhouette_score, high, leiden)
                       if 1 < np.unique(leiden).size < len(leiden) else None),
        "davies_bouldin": (_safe_metric(davies_bouldin_score, high, leiden)
                            if 1 < np.unique(leiden).size < len(leiden) else None),
        "n_clusters": int(np.unique(leiden).size),
    }
    biology = {
        "celltype_asw": (_safe_metric(silhouette_score, high, cell_types)
                         if cell_types is not None and 1 < np.unique(cell_types).size < len(cell_types)
                         else None),
        "annotation_key": cell_type_key if cell_types is not None else None,
        "annotation_status": str(adata.uns.get("annotation_status", "unknown")),
        # Candidate labels inferred from the same clustering are useful audit
        # evidence but are circular and must not masquerade as independent
        # biological validation.
        "independent": bool(cell_type_key == "cell_type" and
                            str(adata.uns.get("annotation_status", "")).startswith("approved")),
    }
    batch = {
        "ilisi": (_safe_metric(normalized_ilisi, high, batches, k) if batches is not None else None),
        "batch_asw": (_safe_metric(silhouette_score, high, batches)
                      if batches is not None and 1 < np.unique(batches).size < len(batches) else None),
        "key": batch_key,
    }
    return {
        "embedding": embedding, "clustering": clustering, "biology": biology, "batch": batch,
        "evaluation": {"n_cells": int(len(selected)), "max_cells": int(max_cells),
                       "n_neighbors": int(k), "representation": "X_pca_harmony",
                       "embedding": "X_umap_after_harmony", "seed": 0},
        "dataset": {"n_cells": int(adata.n_obs), "n_genes": int(adata.n_vars),
                    "n_batches": int(np.unique(batches).size) if batches is not None else 0,
                    "n_celltypes": int(np.unique(cell_types).size) if cell_types is not None else 0},
    }
