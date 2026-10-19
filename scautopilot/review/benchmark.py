"""Objective Scanpy/UMAP benchmarks used to build reviewer evidence."""

from __future__ import annotations

from typing import Any, Dict, Optional
import hashlib
import json

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


def normalized_ilisi(values: np.ndarray, batches: np.ndarray, k: int,
                     neighbors=None) -> Optional[float]:
    unique = np.unique(batches)
    if unique.size < 2:
        return None
    neighbors = _knn_indices(values, k) if neighbors is None else neighbors
    scores = []
    for row in neighbors:
        _, counts = np.unique(batches[row], return_counts=True)
        probabilities = counts / counts.sum()
        scores.append(1.0 / np.square(probabilities).sum())
    raw = float(np.mean(scores))
    return float(np.clip((raw - 1.0) / (unique.size - 1.0), 0.0, 1.0))


def calculate_scanpy_benchmarks(h5ad_path, parameters: Dict[str, Any], max_cells: int = 5000,
                                evaluation_k: int = 15, seed: int = 0,
                                reference_h5ad=None, reference_n_pcs=None) -> Dict[str, Any]:
    import anndata as ad
    from sklearn.manifold import trustworthiness
    from sklearn.metrics import davies_bouldin_score, silhouette_score

    if max_cells < 4 or evaluation_k < 1:
        raise ValueError('benchmark max_cells must be >=4 and evaluation_k must be positive')
    adata = ad.read_h5ad(str(h5ad_path), backed="r")
    reference = None
    try:
        if reference_h5ad is not None:
            reference = ad.read_h5ad(str(reference_h5ad), backed='r')
        return _calculate(adata, parameters, max_cells, evaluation_k, seed,
                          trustworthiness, davies_bouldin_score, silhouette_score,
                          reference, reference_n_pcs)
    finally:
        adata.file.close()
        if reference is not None:
            reference.file.close()


def _calculate(adata, parameters, max_cells, evaluation_k, seed,
               trustworthiness, davies_bouldin_score, silhouette_score,
               reference=None, reference_n_pcs=None):
    required = {"X_pca_harmony", "X_umap_after_harmony"}
    missing = sorted(required - set(adata.obsm.keys()))
    if missing:
        raise ValueError("candidate H5AD lacks representation(s): %s" % ", ".join(missing))
    count = adata.n_obs
    if count < 4:
        raise ValueError("benchmark needs at least four cells")
    if not adata.obs_names.is_unique:
        raise ValueError('benchmark cell IDs must be unique')
    ids = adata.obs_names.astype(str).to_numpy()
    # Stable by cell ID, so reordering rows cannot change the evaluation sample.
    selected = np.asarray(sorted(range(count), key=lambda i:
        hashlib.sha256((str(seed) + '\0' + ids[i]).encode()).digest())[:max_cells])
    n_pcs = int(parameters['n_pcs'])
    if not 1 <= n_pcs <= adata.obsm['X_pca_harmony'].shape[1]:
        raise ValueError('requested PCs exceed stored representation; refusing silent clipping')
    candidate_high = np.asarray(adata.obsm['X_pca_harmony'][selected, :n_pcs])
    evaluation_source = reference if reference is not None else adata
    evaluation_pcs = int(reference_n_pcs) if reference_n_pcs is not None else n_pcs
    if (not evaluation_source.obs_names.is_unique or not evaluation_source.var_names.is_unique or
            set(evaluation_source.obs_names) != set(adata.obs_names) or
            set(evaluation_source.var_names) != set(adata.var_names)):
        raise ValueError('fixed reference requires the same complete cell and feature sets')
    if not 1 <= evaluation_pcs <= evaluation_source.obsm['X_pca_harmony'].shape[1]:
        raise ValueError('fixed evaluation PCs exceed stored reference')
    reference_rows = evaluation_source.obs_names.get_indexer(ids[selected])
    high = np.asarray(evaluation_source.obsm['X_pca_harmony'][reference_rows, :evaluation_pcs])
    low = np.asarray(adata.obsm["X_umap_after_harmony"][selected, :])
    obs = adata.obs.iloc[selected]
    # Trustworthiness requires k < n/2. Both metrics use the same fixed k;
    # candidate graph neighborhood size never changes the evaluation protocol.
    k = min(int(evaluation_k), (len(selected) - 1) // 2)
    if not np.isfinite(high).all() or not np.isfinite(low).all() or not np.isfinite(candidate_high).all():
        raise ValueError('benchmark coordinates must be finite')
    if 'leiden' not in obs or adata.obs['leiden'].isna().any():
        raise ValueError('benchmark needs non-missing Leiden labels')
    leiden = obs["leiden"].astype(str).to_numpy()
    reference_independent = bool(isinstance(adata.uns.get('annotation_reference_independent'), (bool, np.bool_)) and
        adata.uns.get('annotation_reference_independent', False) and
        str(adata.uns.get('annotation_status', '')) in {'approved', 'reviewed'})
    cell_type_key = 'cell_type' if reference_independent and 'cell_type' in obs else (
        "candidate_cell_type" if "candidate_cell_type" in obs else "cell_type")
    cell_types = obs[cell_type_key].astype(str).to_numpy() if cell_type_key in obs else None
    batch_key = next((key for key in ('sample_id', 'sample', 'cohort', 'batch') if key in obs), None)
    batches = obs[batch_key].astype(str).to_numpy() if batch_key and not adata.obs[batch_key].isna().any() else None

    high_knn, low_knn = _knn_indices(high, k), _knn_indices(low, k)
    embedding = {
        "trustworthiness": _safe_metric(trustworthiness, high, low, n_neighbors=k),
        "knn_preservation": float(np.mean([len(set(a) & set(b)) / k for a, b in zip(high_knn, low_knn)])),
    }
    sizes = adata.obs['leiden'].value_counts()
    sizes = sizes[sizes > 0]
    small_cutoff = max(10, int(np.ceil(count * 0.001)))
    clustering = {
        "silhouette": (_safe_metric(silhouette_score, high, leiden)
                       if 1 < np.unique(leiden).size < len(leiden) else None),
        "davies_bouldin": (_safe_metric(davies_bouldin_score, high, leiden)
                            if 1 < np.unique(leiden).size < len(leiden) else None),
        "n_clusters": int(len(sizes)),
        "sampled_n_clusters": int(np.unique(leiden).size),
        "cluster_sizes": {str(key): int(value) for key, value in sizes.items()},
        "small_cluster_cutoff": small_cutoff,
        "small_cluster_cell_fraction": float(sizes[sizes < small_cutoff].sum() / count),
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
        "independent": bool(cell_type_key == 'cell_type' and reference_independent),
    }
    if biology['independent']:
        import pandas as pd
        if adata.obs[cell_type_key].isna().any():
            raise ValueError('independent labels must cover all cells')
        table = pd.crosstab(adata.obs[cell_type_key], adata.obs['leiden'])
        f1 = 2 * table.to_numpy() / (table.sum(axis=1).to_numpy()[:, None] + table.sum(axis=0).to_numpy()[None, :])
        biology['label_best_cluster_f1'] = {str(label): float(score) for label, score in zip(table.index, f1.max(axis=1))}
    candidate_knn = high_knn if np.array_equal(high, candidate_high) else _knn_indices(candidate_high, k)
    batch = {
        "ilisi": (_safe_metric(normalized_ilisi, candidate_high, batches, k, candidate_knn) if batches is not None else None),
        "batch_asw": (_safe_metric(silhouette_score, candidate_high, batches)
                      if batches is not None and 1 < np.unique(batches).size < len(batches) else None),
        "key": batch_key,
        "mixing_method": 'unweighted_fixed_k_inverse_simpson_not_scib_lisi',
        "selection_role": 'diagnostic_only_not_an_optimization_target',
    }
    metadata_keys = [key for key in ('sample_id', 'sample', 'cohort', 'batch', 'donor', 'condition', 'group')
                     if key in adata.obs]
    if biology['independent']:
        metadata_keys.append(cell_type_key)
    identity_rows = adata.obs[sorted(set(metadata_keys))].sort_index().astype('string').fillna('')
    metadata_digest = hashlib.sha256(identity_rows.to_csv().encode()).hexdigest()
    return {
        "embedding": embedding, "clustering": clustering, "biology": biology, "batch": batch,
        "evaluation": {"n_cells": int(len(selected)), "max_cells": int(max_cells),
                       "n_neighbors": int(k), "representation": "X_pca_harmony",
                       "embedding": "X_umap_after_harmony", "seed": int(seed),
                       "requested_n_neighbors": int(evaluation_k),
                       "reference_mode": 'frozen_session_baseline' if reference is not None else 'candidate',
                       "reference_n_pcs": evaluation_pcs,
                       "reference_coordinates_sha256": hashlib.sha256(np.ascontiguousarray(high).tobytes()).hexdigest(),
                       "sampling": "cell_id_sha256_v1",
                       "all_cell_ids_sha256": hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest(),
                       "feature_ids_sha256": hashlib.sha256(json.dumps(sorted(adata.var_names.astype(str))).encode()).hexdigest(),
                       "metadata_sha256": metadata_digest,
                       "cell_ids_sha256": hashlib.sha256(json.dumps(ids[selected].tolist()).encode()).hexdigest()},
        "dataset": {"n_cells": int(adata.n_obs), "n_genes": int(adata.n_vars),
                    "n_batches": int(np.unique(batches).size) if batches is not None else 0,
                    "n_celltypes": int(np.unique(cell_types).size) if cell_types is not None else 0},
    }
