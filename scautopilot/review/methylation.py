"""Bounded retained-representation search for MethSCAn and MethylVI.

No ALLC conversion, count imputation, feature discovery or model training occurs
here. Those are separate signed experiments, not implicit graph-search actions.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .search import compare, fingerprint, validate_selection


def validate_spec(spec):
    required = {'id', 'mode', 'source_run', 'source_task', 'source_h5ad',
                'baseline', 'grids', 'sample_key', 'qc_keys'}
    optional = {'label_key', 'max_rounds', 'patience', 'max_seconds', 'evaluation_cells',
                'evaluation_k', 'seed', 'confirmation_seeds', 'selection',
                'min_seed_ari', 'min_cluster_jaccard', 'stability_tolerance'}
    if not isinstance(spec, dict) or not required <= set(spec) or set(spec) - required - optional:
        raise ValueError('invalid methylation iteration spec fields')
    for key in ('id', 'source_run', 'source_task'):
        if not isinstance(spec[key], str) or not spec[key] or not all(c.isalnum() or c in '._-' for c in spec[key]) or spec[key] in {'.', '..'}:
            raise ValueError('invalid path-safe identifier: ' + key)
    if spec['mode'] not in {'methscan', 'methylvi'}:
        raise ValueError('mode must be methscan or methylvi')
    if not isinstance(spec['source_h5ad'], str) or not spec['source_h5ad']:
        raise ValueError('source_h5ad is required')
    if not isinstance(spec['sample_key'], str) or not spec['sample_key']:
        raise ValueError('sample_key is required')
    if 'label_key' in spec and (not isinstance(spec['label_key'], str) or not spec['label_key']):
        raise ValueError('label_key must be an explicit column name')
    if not isinstance(spec['qc_keys'], list) or any(not isinstance(x, str) or not x for x in spec['qc_keys']):
        raise ValueError('qc_keys must be explicit column names (or [] with missing diagnostics recorded)')
    axes = {'n_pcs', 'n_neighbors', 'resolution', 'min_dist'}
    if set(spec['baseline']) != axes or set(spec['grids']) != axes:
        raise ValueError('baseline/grids must declare exactly n_pcs, n_neighbors, resolution, min_dist')
    for axis in axes:
        values = spec['grids'][axis]
        base = spec['baseline'][axis]
        if isinstance(base, bool) or not isinstance(base, (float, int)) or not math.isfinite(base):
            raise ValueError('baseline values must be finite numbers')
        if not isinstance(values, list) or not values or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError('grid must contain finite numbers: ' + axis)
        if values != sorted(set(values)) or spec['baseline'][axis] not in values:
            raise ValueError('grid must be unique, sorted and include baseline: ' + axis)
        if axis in {'n_pcs', 'n_neighbors'} and any(not isinstance(v, int) or v < 2 for v in values):
            raise ValueError('PC and neighbor grids require integers >= 2')
        if axis == 'resolution' and min(values) <= 0 or axis == 'min_dist' and (min(values) < 0 or max(values) > 1):
            raise ValueError('invalid resolution/min_dist grid')
    if spec['mode'] == 'methylvi' and spec['grids']['n_pcs'] != [spec['baseline']['n_pcs']]:
        raise ValueError('MethylVI latent dimensions are not ordered PCs; changing them requires retraining')
    result = dict(spec)
    for key, default, lower, upper in [('max_rounds', 12, 1, 100), ('patience', 5, 1, 100),
            ('max_seconds', 14400, 1, 604800), ('evaluation_cells', 3000, 20, 5000),
            ('evaluation_k', 15, 2, 100), ('seed', 0, 0, 2**31-1)]:
        value = spec.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
            raise ValueError('invalid budget/evaluation setting: ' + key)
        result[key] = value
    seeds = spec.get('confirmation_seeds', [11, 23])
    if not isinstance(seeds, list) or not 2 <= len(seeds) <= 5 or len(set(seeds)) != len(seeds) or any(isinstance(s, bool) or not isinstance(s, int) or s < 0 or s == result['seed'] for s in seeds):
        raise ValueError('declare 2-5 distinct confirmation seeds different from screening seed')
    result['confirmation_seeds'] = seeds
    for key, default in [('min_seed_ari', 0.8), ('min_cluster_jaccard', 0.5), ('stability_tolerance', 0.05)]:
        value = spec.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('invalid stability threshold: ' + key)
        result[key] = value
    result['selection'] = validate_selection(spec.get('selection', {}))
    return result


def next_trial(best, visited, spec, phase, n_cells, dimensions):
    axes = ['resolution', 'n_neighbors'] + (['n_pcs'] if spec['mode'] == 'methscan' else [])
    if phase == 'layout':
        axes = ['min_dist']
    skipped = []
    for axis in axes:
        grid = spec['grids'][axis]
        index = grid.index(best[axis])
        for offset in (-1, 1):
            if not 0 <= index + offset < len(grid):
                continue
            trial = dict(best, **{axis: grid[index + offset]})
            reason = ('already_evaluated' if fingerprint(trial) in visited else
                      'outside_retained_representation' if trial['n_pcs'] > dimensions else
                      'too_many_neighbors' if trial['n_neighbors'] >= n_cells else None)
            if reason:
                skipped.append({'parameters': trial, 'reason': reason})
            else:
                return trial, axis, skipped
    return None, None, skipped


def guarded_compare(candidate, incumbent, baseline, selection):
    verdict = compare(candidate, incumbent, selection)
    gate = compare(candidate, baseline, selection)
    verdict['baseline_guard'] = gate
    if gate['missing_metrics'] or gate['regressions']:
        verdict.update(selected=False, reason='retain_incumbent_baseline_guard')
    return verdict


def digest_array(values):
    import numpy as np
    a = np.ascontiguousarray(values)
    digest = hashlib.sha256(str((a.shape, a.dtype.str)).encode())
    digest.update(a.tobytes())
    return digest.hexdigest()


def digest_graph(graph):
    graph = graph.tocsr(copy=True)
    graph.sort_indices()
    return hashlib.sha256(''.join(digest_array(a) for a in
        (graph.data, graph.indices, graph.indptr)).encode()).hexdigest()


def source_evidence(project, spec):
    """Read small completed-task evidence; full H5AD hashing happens on compute."""
    from figures_comparison_evidence import read_json, task_evidence, sha, plan_digest
    root = Path(project).resolve()
    directory = root / '.workflow/runs' / spec['source_run']
    plan = read_json(directory / 'plan.json')
    item = next((x for x in plan['tasks'] if x['id'] == spec['source_task']), None)
    if item is None:
        raise ValueError('source task is not in the signed source plan')
    task_evidence(directory, plan, item)
    path = Path(spec['source_h5ad'])
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_file() or not path.is_relative_to(Path(plan['result_dir']).resolve()):
        raise ValueError('source H5AD must exist within source result root')
    record_path = directory / 'tasks' / item['id'] / 'task_outputs.json'
    record = read_json(record_path)
    artifacts = [Path(p).resolve() for p in record.get('artifacts', [])]
    if not any(path == p or p.is_dir() and path.is_relative_to(p) for p in artifacts):
        raise ValueError('source H5AD is not owned by the completed task artifacts')
    return {'source_h5ad': str(path), 'source_plan_sha256': plan_digest(directory / 'plan.json'),
            'source_task_outputs_sha256': sha(record_path),
            'source_status_sha256': sha(directory / 'tasks' / item['id'] / 'task_status.json'),
            'source_stat': {'size': path.stat().st_size, 'mtime_ns': path.stat().st_mtime_ns,
                            'ctime_ns': path.stat().st_ctime_ns}}


def read_representation(path, spec):
    import anndata as ad
    import numpy as np
    from umap.umap_ import find_ab_params
    backed = ad.read_h5ad(path, backed='r')
    try:
        key = 'X_pca' if spec['mode'] == 'methscan' else 'X_methylVI'
        cluster = 'leiden' if spec['mode'] == 'methscan' else 'methylVI_leiden'
        prior_iteration = 'iteration_selected_parameters' in backed.uns
        if prior_iteration:
            if backed.uns.get('iteration_mode') != spec['mode']:
                raise ValueError('cannot reinterpret the selected representation as another mode')
            key, cluster = 'X_rep', 'iteration_leiden'
        rep = np.asarray(backed.obsm[key]).copy()
        if rep.ndim != 2 or rep.shape[0] != backed.n_obs or not np.isfinite(rep).all() or not backed.obs_names.is_unique:
            raise ValueError('source representation/cell IDs invalid')
        if backed.n_obs < 20 or spec['baseline']['n_pcs'] > rep.shape[1] or spec['baseline']['n_neighbors'] >= backed.n_obs:
            raise ValueError('insufficient cells or retained dimensions')
        if spec['mode'] == 'methylvi' and spec['baseline']['n_pcs'] != rep.shape[1]:
            raise ValueError('use all MethylVI latent dimensions, never truncate them as PCs')
        neighbors = backed.uns['neighbors']
        params = neighbors['params']
        if params.get('use_rep') != key or params.get('n_neighbors') != spec['baseline']['n_neighbors'] or params.get('metric', 'euclidean') != 'euclidean':
            raise ValueError('baseline neighbor parameters do not match source')
        if int(params.get('n_pcs') or rep.shape[1]) != spec['baseline']['n_pcs']:
            raise ValueError('baseline dimensions do not match source graph')
        source_resolution = (backed.uns['iteration_selected_parameters']['resolution'] if prior_iteration
                             else backed.uns[cluster]['params']['resolution'])
        if source_resolution != spec['baseline']['resolution']:
            raise ValueError('baseline resolution does not match source')
        a, b = find_ab_params(1.0, spec['baseline']['min_dist'])
        if not np.allclose([a, b], [backed.uns['umap']['params'][x] for x in ('a', 'b')], rtol=1e-5):
            raise ValueError('baseline min_dist/spread do not match saved UMAP; spread must be 1')
        obs = backed.obs.copy()
        if spec['sample_key'] not in obs or obs[spec['sample_key']].isna().any():
            raise ValueError('explicit sample metadata is missing')
        for field in spec['qc_keys'] + ([spec['label_key']] if spec.get('label_key') else []):
            if field not in obs:
                raise ValueError('requested diagnostic column absent: ' + field)
        small = ad.AnnData(obs=obs)
        small.obsm['X_rep'] = rep
        small.obsm['X_umap'] = np.asarray(backed.obsm['X_umap']).copy()
        if not np.isfinite(small.obsm['X_umap']).all():
            raise ValueError('nonfinite source UMAP')
        small.obs['iteration_leiden'] = obs[cluster].astype(str).to_numpy()
        small.obsp['connectivities'] = backed.obsp[neighbors['connectivities_key']].copy()
        small.obsp['distances'] = backed.obsp[neighbors['distances_key']].copy()
        small.uns['neighbors'] = dict(neighbors)
        small.uns['neighbors'].update(connectivities_key='connectivities', distances_key='distances')
        small.uns['neighbors']['params'] = dict(params, use_rep='X_rep', n_pcs=spec['baseline']['n_pcs'])
        small.uns['umap'] = dict(backed.uns['umap'])
        return small
    finally:
        backed.file.close()


def derive(parent, old, new, seed):
    import scanpy as sc
    result = parent.copy()
    changed = {x for x in old if old[x] != new[x]}
    graph_changed = bool(changed & {'n_pcs', 'n_neighbors'})
    if graph_changed:
        sc.pp.neighbors(result, use_rep='X_rep', n_pcs=new['n_pcs'],
                        n_neighbors=new['n_neighbors'], random_state=seed)
    if graph_changed or 'resolution' in changed:
        sc.tl.leiden(result, resolution=new['resolution'], key_added='iteration_leiden', random_state=seed)
    if graph_changed or 'min_dist' in changed:
        sc.tl.umap(result, min_dist=new['min_dist'], spread=1.0, random_state=seed)
    assert digest_array(result.obsm['X_rep']) == digest_array(parent.obsm['X_rep'])
    if not graph_changed:
        assert digest_graph(result.obsp['connectivities']) == digest_graph(parent.obsp['connectivities'])
    if changed == {'resolution'}:
        assert digest_array(result.obsm['X_umap']) == digest_array(parent.obsm['X_umap'])
    if changed == {'min_dist'}:
        assert result.obs['iteration_leiden'].equals(parent.obs['iteration_leiden'])
    return result


def metrics(adata, parameters, idx, ref, ref_knn, k, run_id):
    import numpy as np
    from sklearn.metrics import silhouette_score, davies_bouldin_score
    from sklearn.manifold import trustworthiness
    from sklearn.neighbors import NearestNeighbors
    labels = adata.obs['iteration_leiden'].astype(str).to_numpy()
    sampled = labels[idx]
    sizes = adata.obs['iteration_leiden'].value_counts()
    silhouette = db = None
    if 1 < len(set(sampled)) < len(sampled):
        silhouette = float(silhouette_score(ref, sampled))
        db = float(davies_bouldin_score(ref, sampled))
    coords = np.asarray(adata.obsm['X_umap'])[idx]
    knn = NearestNeighbors(n_neighbors=k).fit(coords).kneighbors(return_distance=False)
    return {'run_id': run_id, 'parameters': parameters,
            'clustering': {'silhouette': silhouette, 'davies_bouldin': db,
                'n_clusters': len(sizes), 'small_cluster_cell_fraction': float(sizes[sizes < max(10, 0.001 * len(labels))].sum() / len(labels))},
            'embedding': {'trustworthiness': float(trustworthiness(ref, coords, n_neighbors=k)),
                'knn_preservation': float(np.mean([len(set(a) & set(b)) / k for a, b in zip(knn, ref_knn)]))},
            'biology': {'independent': False}}


def stability(adata, parameters, seeds):
    import numpy as np
    import scanpy as sc
    from sklearn.metrics import adjusted_rand_score
    labels = adata.obs['iteration_leiden'].astype(str).to_numpy()
    aris, per_cluster = [], {label: [] for label in sorted(set(labels))}
    for seed in seeds:
        trial = adata.copy()
        sc.pp.neighbors(trial, use_rep='X_rep', n_pcs=parameters['n_pcs'],
                        n_neighbors=parameters['n_neighbors'], random_state=seed)
        sc.tl.leiden(trial, resolution=parameters['resolution'], random_state=seed, key_added='iteration_leiden')
        other = trial.obs['iteration_leiden'].astype(str).to_numpy()
        aris.append(float(adjusted_rand_score(labels, other)))
        for label in per_cluster:
            mask = labels == label
            per_cluster[label].append(max(float(np.sum(mask & (other == alt)) / np.sum(mask | (other == alt))) for alt in set(other)))
    return {'seeds': seeds, 'ari': aris, 'median_ari': float(np.median(aris)),
            'cluster_best_jaccard': per_cluster,
            'minimum_cluster_median_jaccard': min(float(np.median(v)) for v in per_cluster.values()),
            'scope': 'graph_and_leiden_only_not_model_training_or_feature_discovery'}


def execute(project, spec, output, expected_source=None):
    from _common import host_role, write_json
    if host_role() == 'submit':
        raise ValueError('methylation numerical iteration requires a compute allocation')
    import time
    import numpy as np
    import pandas as pd
    from sklearn.neighbors import NearestNeighbors
    from figures_comparison_evidence import sha
    spec = validate_spec(spec)
    evidence = source_evidence(project, spec)
    if expected_source is not None and evidence != expected_source:
        raise ValueError('source evidence changed after planning')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'spec.json', spec)
    evidence['source_h5ad_sha256'] = sha(evidence['source_h5ad'])
    started = time.monotonic()
    baseline = read_representation(evidence['source_h5ad'], spec)
    # Exact cell-ID hash sampling is deterministic even if input order changes.
    idx = np.array(sorted(range(baseline.n_obs), key=lambda i: hashlib.sha256(
        ('%s:%s' % (spec['seed'], baseline.obs_names[i])).encode()).digest())[:spec['evaluation_cells']])
    ref = baseline.obsm['X_rep'][idx, :spec['baseline']['n_pcs']]
    k = min(spec['evaluation_k'], (len(idx) - 1) // 2)
    ref_knn = NearestNeighbors(n_neighbors=k).fit(ref).kneighbors(return_distance=False)
    evidence.update(representation_sha256=digest_array(baseline.obsm['X_rep']),
        cell_ids_sha256=hashlib.sha256('\n'.join(baseline.obs_names).encode()).hexdigest(),
        evaluation_cell_ids=baseline.obs_names[idx].tolist(), evaluation_k=k,
        reference_space='fixed_source_representation_not_each_candidate_UMAP')
    write_json(output / 'source_evidence.json', evidence)
    best = baseline
    best_state = base_state = metrics(best, spec['baseline'], idx, ref, ref_knn, k, 'round000')
    visited, rows, streak, phase, tried = set(), [], 0, 'science', set()
    current, state, parent_id, axis = best, best_state, None, None
    stop = None
    while True:
        round_dir = output / state['run_id']
        round_dir.mkdir()
        verdict = {'selected': True, 'reason': 'initial_reference'} if not rows else guarded_compare(state, best_state, base_state, spec['selection'])
        if verdict['selected']:
            best, best_state, streak = current, state, 0
        else:
            streak += 1
        state.update(parent_id=parent_id, changed_axis=axis, phase=phase,
            graph_sha256=digest_graph(current.obsp['connectivities']),
            umap_sha256=digest_array(current.obsm['X_umap']))
        write_json(round_dir / 'evaluation.json', dict(state=state, decision=verdict))
        pd.DataFrame({'cell_id': current.obs_names, 'leiden': current.obs['iteration_leiden'].astype(str).to_numpy(),
            'UMAP1': current.obsm['X_umap'][:, 0], 'UMAP2': current.obsm['X_umap'][:, 1]}).to_csv(round_dir / 'coordinates.tsv', sep='\t', index=False)
        rows.append(dict(state=state, decision=verdict))
        visited.add(fingerprint(state['parameters']))
        if axis:
            tried.add(axis)
        params, next_axis, skipped = next_trial(best_state['parameters'], visited, spec, phase, baseline.n_obs, baseline.obsm['X_rep'].shape[1])
        feasible_axes = {name for name in ('resolution', 'n_neighbors', 'n_pcs') if len(spec['grids'][name]) > 1}
        if phase == 'science' and (params is None or streak >= spec['patience'] and feasible_axes <= tried):
            phase, streak = 'layout', 0
            params, next_axis, more = next_trial(best_state['parameters'], visited, spec, phase, baseline.n_obs, baseline.obsm['X_rep'].shape[1])
            skipped += more
        if any(base_state['clustering'][m] is None for m in ('silhouette', 'davies_bouldin')):
            stop = 'baseline_metrics_incomplete_review_required'
        elif len(rows) >= spec['max_rounds']:
            stop = 'round_budget'
        elif time.monotonic() - started >= spec['max_seconds']:
            stop = 'walltime_budget'
        elif params is None:
            stop = 'local_frontier_exhausted'
        elif phase == 'layout' and streak >= spec['patience']:
            stop = 'layout_patience_budget'
        write_json(output / 'selection_summary.json', {'status': 'screening' if not stop else 'screened',
            'incumbent': best_state['run_id'], 'parameters': best_state['parameters'],
            'stop_reason': stop, 'rounds': len(rows), 'skipped': skipped,
            'biological_approval': False, 'global_optimum_claimed': False})
        if stop:
            break
        parent_id, axis = best_state['run_id'], next_axis
        current = derive(best, best_state['parameters'], params, spec['seed'])
        state = metrics(current, params, idx, ref, ref_knn, k, 'round%03d' % len(rows))
    # Independent graph seeds do NOT constitute independent MethylVI training seeds.
    confirm = {}
    final_status = 'requires_review'
    if time.monotonic() - started < spec['max_seconds'] and stop != 'baseline_metrics_incomplete_review_required':
        confirm['baseline'] = stability(baseline, spec['baseline'], spec['confirmation_seeds'])
        confirm['screened_best'] = (confirm['baseline'] if best is baseline else
            stability(best, best_state['parameters'], spec['confirmation_seeds']))
        candidate_check, base_check = confirm['screened_best'], confirm['baseline']
        stable = (candidate_check['median_ari'] >= max(spec['min_seed_ari'], base_check['median_ari'] - spec['stability_tolerance'])
                  and candidate_check['minimum_cluster_median_jaccard'] >= spec['min_cluster_jaccard'])
        confirm['passed'] = stable
        if not stable:
            best, best_state = baseline, base_state
        else:
            final_status = 'screened_seed_checked_requires_biological_review'
    else:
        confirm['skipped_reason'] = 'budget_or_incomplete_metrics'
        best, best_state = baseline, base_state
    write_json(output / 'seed_confirmation.json', confirm)
    # Retained representations cannot establish model or feature-level adequacy.
    diagnostics = {'missing_qc': not bool(spec['qc_keys']), 'representation_qc_spearman': {}}
    for column in spec['qc_keys']:
        numeric = pd.to_numeric(baseline.obs[column], errors='coerce')
        values = [pd.Series(baseline.obsm['X_rep'][:, j], index=baseline.obs_names).corr(numeric, method='spearman')
                  for j in range(baseline.obsm['X_rep'].shape[1])]
        diagnostics['representation_qc_spearman'][column] = [float(v) if np.isfinite(v) else None for v in values]
    write_json(output / 'diagnostics.json', diagnostics)
    counts = pd.crosstab(best.obs['iteration_leiden'], best.obs[spec['sample_key']])
    counts.to_csv(output / 'cluster_sample_counts.tsv', sep='\t')
    if spec.get('label_key'):
        pd.crosstab(best.obs['iteration_leiden'], best.obs[spec['label_key']]).to_csv(output / 'cluster_label_counts.tsv', sep='\t')
    best.uns['iteration_source'] = json.dumps(evidence, sort_keys=True)
    best.uns['iteration_selected_parameters'] = best_state['parameters']
    best.uns['iteration_mode'] = spec['mode']
    best.write_h5ad(output / 'selected_embedding.h5ad', compression='gzip')
    pd.DataFrame([dict(round=r['state']['run_id'], parent=r['state']['parent_id'], axis=r['state']['changed_axis'],
        **r['state']['parameters'], **r['state']['clustering'], **r['state']['embedding'],
        selected=r['decision']['selected'], reason=r['decision']['reason']) for r in rows]).to_csv(output / 'candidate_comparison.tsv', sep='\t', index=False)
    render(project, baseline, best, spec, output)
    summary = {'status': final_status, 'incumbent': best_state['run_id'], 'parameters': best_state['parameters'],
        'selected_embedding': str(output / 'selected_embedding.h5ad'), 'stop_reason': stop, 'rounds': len(rows),
        'scope': 'retained_representation_graph_and_layout', 'model_retrained': False,
        'features_recomputed': False, 'biological_approval': False, 'global_optimum_claimed': False,
        'outstanding_checks': ['coverage_and_sample_confounding', 'rare_population_and_marker_support',
            'feature_or_model_experiment_if_latent_defect_persists', 'visual_review'],
        'elapsed_seconds': time.monotonic() - started}
    checked_source = source_evidence(project, spec)
    if checked_source != {k: evidence[k] for k in checked_source}:
        raise ValueError('source changed during iteration')
    write_json(output / 'selection_summary.json', summary)
    (output / 'Report.md').write_text(
        '# Methylation iteration / 甲基化迭代\n\n'
        '- Mode: `%s`; source: `%s` / `%s`.\n'
        '- Selected: `%s`; stop: `%s`; evaluated rounds: %d.\n'
        '- Status: `%s`. Computation is not biological or visual approval.\n'
        '- Retained representation only; no ALLC conversion, feature discovery, '
        'DMR inference or MethylVI retraining.\n'
        '- [Parameters and decisions](candidate_comparison.tsv), '
        '[seed confirmation](seed_confirmation.json), [diagnostics](diagnostics.json), '
        '[selected representation](selected_embedding.h5ad), [figures](figures_comparison/).\n'
        '- Source results and approved annotations remain unchanged.\n' %
        (spec['mode'], spec['source_run'], spec['source_task'], best_state['run_id'], stop, len(rows), final_status),
        encoding='utf-8')
    artifacts = [{'path': str(p.relative_to(output)), 'sha256': sha(p), 'bytes': p.stat().st_size}
                 for p in sorted(output.rglob('*')) if p.is_file()]
    write_json(output / 'iteration_manifest.json', {'schema_version': 1, 'status': 'complete',
        'source': evidence, 'spec': spec, 'summary': summary, 'artifacts': artifacts, 'visual_review': 'pending'})
    return summary


def render(project, baseline, selected, spec, output):
    import sys
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import scanpy as sc
    sys.path.insert(0, str(Path(project) / 'Scripts/Common'))
    from embedding_plot import save_embedding
    directory = output / 'figures_comparison'
    directory.mkdir()
    columns = ['iteration_leiden', spec['sample_key']] + ([spec['label_key']] if spec.get('label_key') else [])
    for index, column in enumerate(columns):
        # Partition IDs are not biological correspondences across different runs.
        for name, obj in [('source', baseline), ('selected', selected)]:
            fig = sc.pl.umap(obj, color=column, show=False, return_fig=True,
                             title='%s / %s (ordinary UMAP)' % (name, column))
            save_embedding(fig, directory / ('%s_panel%d.png' % (name, index + 1)))
            plt.close(fig)
