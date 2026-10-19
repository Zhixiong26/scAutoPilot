#!/usr/bin/env python3
"""Render immutable batch atlases from existing scientific results only.

Presentation geometry follows the reference batch atlases: square limits, fixed
point order, direct vector artists, and separate ordinary/supervised views.
Source adaptation and transactional delivery are native workflow infrastructure.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import shutil
import socket
import sys
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from _common import WorkflowError, login_host_refusal, submit_host_execution_allowed, write_json
from figures_comparison_evidence import (ROUTES, delivery_record, read_json, sha,
                                         task_evidence, validate_manifest)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def coordinate_hash(ids, xy):
    import numpy as np
    values = np.ascontiguousarray(xy, dtype='<f8')
    digest = hashlib.sha256()
    digest.update(fingerprint(list(ids)).encode())
    digest.update(json.dumps(list(values.shape)).encode())
    digest.update(values.tobytes())
    return digest.hexdigest()


def safe_name(value):
    import re
    text = str(value)
    return re.sub(r'[^a-zA-Z0-9_.-]', '_', text)[:100] + '_' + fingerprint(text)[:8]


class Sources:
    def __init__(self, root, plan, spec):
        self.root, self.plan, self.spec = root, plan, spec
        self.run_dir = root / '.workflow/runs' / plan['run_id']
        self.records = {}
        self.context = None
        self.owners = {}
        for item in plan['tasks']:
            if item['id'] in ('workflow_summary', 'figures_comparison'):
                continue
            task_evidence(self.run_dir, plan, item)
            self._register(self.run_dir / 'tasks' / item['id'] / 'task_status.json', 'task_evidence')
            self._register(self.run_dir / 'tasks' / item['id'] / 'task.COMPLETE', 'task_evidence')
            owner_dir, owner_plan, owner_item = self.run_dir, plan, item
            reuse = spec.get('source_runs', {}).get(item['id'])
            if reuse:
                owner_dir = root / '.workflow/runs' / reuse['run_id']
                owner_plan = read_json(owner_dir / 'plan.json')
                owner_item = next((x for x in owner_plan['tasks'] if x['id'] == reuse['task_id']), None)
                if owner_item is None or owner_item.get('parameters', {}) != item.get('parameters', {}):
                    raise ValueError('borrowed model parameters do not match: %s' % item['id'])
                task_evidence(owner_dir, owner_plan, owner_item)
                for name in ('task_status.json', 'task.COMPLETE'):
                    self._register(owner_dir / 'tasks' / owner_item['id'] / name, 'task_evidence')
                self._register(owner_dir / 'plan.json', 'task_evidence')
            self.owners[item['id']] = {'run_id': owner_plan['run_id'], 'task_id': owner_item['id'],
                'input_signature': owner_plan['input_signature'], 'code_signature': owner_plan['code_signature'],
                'result_dir': str(Path(owner_plan['result_dir']).resolve())}
        self._register(self.run_dir / 'plan.json', 'task_evidence')

    def _register(self, path, kind):
        path = Path(path).absolute()
        if not path.is_file():
            raise ValueError('source file absent: %s' % path)
        entry = {'path': str(path), 'resolved_path': str(path.resolve()), 'sha256': sha(path),
                 'bytes': path.stat().st_size, 'kind': kind}
        if self.context:
            entry.update(source_task=self.context, **self.owners[self.context])
        old = self.records.get(str(path))
        if old and (old['sha256'] != entry['sha256'] or old['resolved_path'] != entry['resolved_path']):
            raise ValueError('source changed while reading: %s' % path)
        self.records[str(path)] = entry
        return path

    def file(self, path):
        path = Path(path).absolute()
        if self.context:
            permitted = Path(self.owners[self.context]['result_dir'])
            if not path.resolve().is_relative_to(permitted):
                raise ValueError('unregistered cross-run source: %s' % path)
        return self._register(path, 'derived_input')

    def json(self, path):
        return read_json(self.file(path))

    def verify(self):
        for value in self.records.values():
            path = Path(value['path'])
            if str(path.resolve()) != value['resolved_path'] or sha(path) != value['sha256']:
                raise ValueError('Source changed during rendering: %s' % path)


def embedding(source, path):
    import anndata as ad
    import numpy as np
    data = ad.read_h5ad(source.file(path), backed='r')
    try:
        obs = data.obs.copy()
        obs.index = obs.index.astype(str)
        if obs.index.has_duplicates or not len(obs) or any(not x for x in obs.index):
            raise ValueError('invalid/duplicate embedding cell IDs')
        coordinates = {key: np.asarray(value).copy() for key, value in data.obsm.items()
                       if key.startswith('X_umap')}
        # Only presentation metadata is retained; never load X or training weights.
        colors = {key: list(value) for key, value in data.uns.items()
                  if key.endswith(('_colors', '_display_order', '_display_palette'))}
    finally:
        data.file.close()
    return obs, coordinates, colors


def palette_for(obs, colors, column, methscan=False):
    import anndata as ad
    import matplotlib.colors as mc
    import matplotlib.pyplot as plt
    import pandas as pd
    import scanpy as sc
    series = obs[column]
    if series.isna().any():
        raise ValueError('missing labels in %s; explicit source annotation required' % column)
    stored_order = colors.get(column + '_display_order')
    stored_palette = colors.get(column + '_display_palette')
    if stored_order is not None or stored_palette is not None:
        if stored_order is None or stored_palette is None or len(stored_order) != len(stored_palette):
            raise ValueError('source display palette/order mismatch: %s' % column)
        categories = list(map(str, stored_order))
        if (not categories or any(not value.strip() for value in categories)
                or len(categories) != len(set(categories))
                or not set(series.astype(str)) <= set(categories)):
            raise ValueError('source display palette lacks unique labels covering observations: %s' % column)
        palette = [mc.to_hex(x) for x in stored_palette]
        origin = 'source_display_palette'
    elif methscan and colors.get(column + '_colors') is None:
        categories = sorted(series.astype(str).unique())
        palette = [mc.to_hex(plt.get_cmap('tab20').colors[i % 20]) for i in range(len(categories))]
        origin = 'source_methscan_sorted_tab20'
    else:
        if not isinstance(series.dtype, pd.CategoricalDtype):
            from natsort import natsorted
            series = pd.Series(pd.Categorical(series.astype(str), categories=natsorted(series.astype(str).unique())),
                               index=obs.index)
        categories = list(map(str, series.cat.categories))
        stored = colors.get(column + '_colors')
        if stored is not None:
            if len(stored) != len(categories):
                raise ValueError('source palette/category length mismatch: %s' % column)
            palette, origin = [mc.to_hex(x) for x in stored], 'source_uns'
        else:
            # Scanpy renamed this helper in newer releases. Saved palettes do
            # not need it at all; reconstruct only in the source environment.
            from scanpy.plotting import _utils
            set_defaults = getattr(_utils, '_set_default_colors_for_categorical_obs', None)
            if set_defaults is None:
                set_defaults = _utils.set_default_colors_for_categorical_obs
            temporary = ad.AnnData(obs=pd.DataFrame({column: series}, index=obs.index))
            set_defaults(temporary, column)
            palette = [mc.to_hex(x) for x in temporary.uns[column + '_colors']]
            origin = 'reconstructed_from_source_scanpy_rule'
    return dict(zip(categories, palette)), categories, {'origin': origin, 'scanpy_version': sc.__version__}


def make_panel(source, path, obs, coordinates, colors, key, column, model, route,
               title, annotation_status='source', methscan=False):
    import numpy as np
    if key not in coordinates or column not in obs:
        raise ValueError('embedding lacks %s / %s: %s' % (key, column, path))
    xy = coordinates[key]
    if xy.shape != (len(obs), 2) or not np.isfinite(xy).all():
        raise ValueError('invalid coordinates: %s: %s' % (path, key))
    palette, categories, origin = palette_for(obs, colors, column, methscan)
    ids, labels = obs.index.tolist(), obs[column].astype(str).tolist()
    return {'route': route, 'model': model, 'source': str(path), 'basis': key, 'column': column,
            'title': title, 'annotation_status': annotation_status, 'ids': ids, 'xy': xy,
            'labels': labels, 'palette': palette, 'categories': categories, 'palette_source': origin,
            'coordinate_sha256': coordinate_hash(ids, xy), 'cell_ids_sha256': fingerprint(ids),
            'labels_sha256': fingerprint(labels)}


def supervised_panels(source, model_dir, ordinary, model, route, spec):
    import numpy as np
    summary = source.json(model_dir / 'results/supervised_umap/supervised_umap_summary.json')
    target = spec['supervised_target_key']
    if summary.get('target_key') != target or summary.get('target_weights') != spec['weights']:
        raise ValueError('supervised parameters differ from plan: %s' % model)
    obs, coords, colors = ordinary
    if summary.get('cells') != len(obs) or target not in obs:
        raise ValueError('supervised source cell/target mismatch: %s' % model)
    placeholders = {'', 'na', 'nan', 'none', 'n/a', 'unknown', 'unannotated', 'unassigned',
                    'requires_review', 'requires review'}
    real_labels = {str(x).strip() for x in obs[target].dropna() if str(x).strip().lower() not in placeholders}
    if summary.get('status') == 'skipped':
        if len(real_labels) >= 2 or not summary.get('reason') or summary.get('coordinate_files') or summary.get('figure_files'):
            raise ValueError('unsupported supervised skip: %s' % model)
        return [], summary['reason']
    if summary.get('status') != 'complete' or len(real_labels) < 2:
        raise ValueError('supervised stage lacks valid completion: %s' % model)
    path = model_dir / 'results/supervised_umap/methylvi_supervised_umap.h5ad'
    s_obs, s_coords, s_colors = embedding(source, path)
    if set(s_obs.index) != set(obs.index):
        raise ValueError('ordinary/supervised cell sets differ: %s' % model)
    order = s_obs.index.get_indexer(obs.index)
    s_obs = s_obs.iloc[order]
    s_coords = {k: v[order] for k, v in s_coords.items()}
    if s_obs[target].astype(str).tolist() != obs[target].astype(str).tolist():
        raise ValueError('supervised labels differ from ordinary: %s' % model)
    panels = [make_panel(source, model_dir / 'results/methylvi_embedding.h5ad', obs, coords, colors,
                         'X_umap', target, model, route, model + '\nordinary')]
    for weight in spec['weights']:
        key = 'X_umap_target_weight_' + ('%g' % weight).replace('.', 'p')
        panels.append(make_panel(source, path, s_obs, s_coords, s_colors, key, target, model, route,
                                 model + '\ntarget weight=%g' % weight))
    return panels, None


def build_specs(root, plan, spec, source):
    import numpy as np
    import pandas as pd
    result = Path(plan['result_dir'])
    groups, coverage, dmr_files = {}, [], []
    reasons = {name: [] for name in ROUTES}
    selected = spec['routes']
    for item in spec['models']:
        task, parameters = item['id'], item['parameters']
        source.context = task
        route, rows, group = None, [], None
        if task == 'scanpy':
            route, group = 'scanpy', 'scanpy_ordinary'
            summary = source.json(result / 'scanpy/completion_summary.json')
            paths = [Path(x) for x in summary['artifacts'] if str(x).endswith('.h5ad')]
            if len(paths) != 1 or summary.get('run_id') != plan['run_id']:
                raise ValueError('Scanpy must identify one run-scoped analysis h5ad')
            path = paths[0]
            obs, coords, colors = embedding(source, path)
            annotation = summary.get('annotation_key')
            expected_annotation = 'cell_type' if summary.get('annotation_status') == 'reviewed' else 'candidate_cell_type'
            if annotation != expected_annotation:
                raise ValueError('Scanpy annotation identity/status inconsistent')
            params = source.json(summary['parameters'])
            if 'cohort_colors' not in colors:
                cohorts = obs['cohort'].cat.categories if isinstance(obs['cohort'].dtype, pd.CategoricalDtype) else sorted(obs['cohort'].unique())
                sample_colors = params.get('sample_palette', [])
                if len(sample_colors) < len(cohorts):
                    raise ValueError('Scanpy source sample palette absent')
                colors['cohort_colors'] = sample_colors[:len(cohorts)]
            rows = [make_panel(source, path, obs, coords, colors, 'X_umap_after_harmony', col,
                               task, route, '%s\n%s (%s)' % (task, col, summary['annotation_status']),
                               summary['annotation_status']) for col in (annotation, 'leiden', 'cohort')]
        elif task.startswith('methscan_vmr_'):
            route, group = 'methscan_vmr', 'methscan_vmr_ordinary'
            directory = result / 'methscan/06_scanpy' / ('var_%s' % parameters['threshold'])
            path = directory / 'objects/methscan_vmr.h5ad'
            obs, coords, colors = embedding(source, path)
            table = pd.read_csv(source.file(directory / 'tables/cell_embedding.tsv'), sep='\t', index_col=0, dtype=str)
            table.index = table.index.astype(str)
            if table.index.has_duplicates or set(table.index) != set(obs.index):
                raise ValueError('VMR table/object cell sets differ')
            table = table.loc[obs.index]
            if not np.allclose(table[['UMAP1', 'UMAP2']].to_numpy(dtype=float), coords['X_umap'], rtol=1e-6, atol=1e-6):
                raise ValueError('VMR table/object coordinates differ')
            parameters_record = source.json(directory / 'run_parameters.json')
            authority = source.file(result / 'methscan/03_filtered/column_header.txt').read_text().splitlines()
            if len(authority) != len(set(authority)) or not set(obs.index) <= set(authority):
                raise ValueError('VMR cells are not a valid subset of filtered inputs')
            if parameters_record.get('retained_cells') != len(obs):
                raise ValueError('VMR retained_cells differs from embedding')
            qc = pd.read_csv(source.file(directory / 'tables/cell_missingness_qc.tsv'), sep='\t', index_col=0, dtype=str)
            qc.index = qc.index.astype(str)
            retained = set(qc.index[qc['pass_min_observed_vmrs'].astype(str).str.lower() == 'true'])
            if retained != set(obs.index):
                raise ValueError('VMR cell QC disagrees with retained embedding')
            columns = ['rna_cell_type', 'leiden', 'sample_id']
            if 'rna_cell_type' not in obs:
                columns.remove('rna_cell_type')
                reasons[route].append(task + ': cell-type panel not applicable; source has no rna_cell_type')
            for col in columns:
                if table[col].astype(str).tolist() != obs[col].astype(str).tolist():
                    raise ValueError('VMR table/object labels differ: ' + col)
            rows = [make_panel(source, path, obs, coords, colors, 'X_umap', col, task, route,
                               task + '\n' + col, methscan=True) for col in columns]
        elif task == 'allcools_features':
            route, group = 'allcools', 'allcools_ordinary'
            # Only the maximum target is clustered; smaller inputs are nested subsets.
            feature_tasks = [x for x in plan['tasks'] if x['id'] == 'figures_comparison'][0]
            maximum = feature_tasks['parameters']['allcools_max_features']
            directory = result / 'methylvi/allcools' / ('features_%d' % maximum)
            path = directory / 'allcools.h5ad'
            source.json(directory / 'cluster_summary.json')
            obs, coords, colors = embedding(source, path)
            rows = [make_panel(source, path, obs, coords, colors, 'X_umap', col, task, route,
                               'ALLCools native\n' + col) for col in ('manual_celltype', 'L1', 'sample_id')]
        elif task == 'methscan_hypo_heatmaps':
            route = 'methscan_dmr'
            summary = source.json(result / 'methscan/hypo_dmr_heatmap_summary.json')
            plots = summary.get('plots', {})
            if summary.get('status') != 'complete' or plots.get('status') != 'complete':
                raise ValueError('DMR heatmap summary not complete')
            if not plots.get('samples'):
                raise ValueError('DMR heatmap summary has no sample coverage')
            seen = set()
            for row in plots['samples']:
                sample = row['sample_id']
                if sample in seen:
                    raise ValueError('duplicate DMR sample in summary')
                seen.add(sample)
                if row.get('status') == 'no_dmrs' and row.get('dmrs') == 0:
                    reasons[route].append(sample + ': no DMRs')
                    continue
                if row.get('status') != 'complete' or row.get('dmrs', 0) <= 0:
                    raise ValueError('invalid DMR sample status: ' + sample)
                for key in ('mean_ratio_plot', 'zscore_plot', 'zscore_compressed_colorbar_plot', 'zscore_mean_plot'):
                    path = source.file(row[key])
                    dmr_files.append({'path': path, 'sample': sample, 'kind': key,
                                      'target': 'dmr/' + safe_name(sample) + '/' + key + path.suffix})
        elif task.startswith('methylvi_') and 'features_' not in task:
            if task.startswith('methylvi_allcools_'):
                route = 'methylvi_allcools'
                directory = result / 'methylvi/allcools' / ('features_%s' % parameters['features'])
                group = route + '_ordinary'
            else:
                route = 'methylvi_vmr_dmr' if task.startswith('methylvi_vmr_dmr_') else 'methylvi_vmr'
                directory = result / 'methylvi' / ('vmr_dmr' if route.endswith('_dmr') else 'vmr') / ('var_%s' % parameters['threshold']) / ('features_%s' % parameters['features'])
                group = route + '_features_%s_ordinary' % parameters['features']
            path = directory / 'results/methylvi_embedding.h5ad'
            obs, coords, colors = embedding(source, path)
            rows = [make_panel(source, path, obs, coords, colors, 'X_umap', col, task, route,
                               task + '\n' + col) for col in ('cell_type', 'methylVI_leiden', 'sample_id')]
            weighted, reason = supervised_panels(source, directory, (obs, coords, colors), task, route, spec)
            if reason:
                reasons[route].append(task + ': supervised not applicable: ' + reason)
            else:
                groups.setdefault(group.replace('_ordinary', '_supervised'), []).append(weighted)
        if rows:
            groups.setdefault(group, []).append(rows)
    source.context = None
    for route in ROUTES:
        count = sum(1 for group in groups.values() for row in group if row and row[0]['route'] == route)
        if route == 'methscan_dmr':
            count += len(dmr_files)
        coverage.append({'route': route, 'selected': bool(selected.get(route)), 'entries': count,
                         'status': 'not_selected' if not selected.get(route) else ('rendered' if count else 'not_applicable'),
                         'reason': '; '.join(reasons[route])})
        if selected.get(route) and count == 0 and not reasons[route]:
            raise ValueError('selected route has no delivery or explicit reason: ' + route)
    return groups, coverage, dmr_files


def draw(ax, panel):
    import numpy as np
    from matplotlib.lines import Line2D
    xy = panel['xy']
    order = np.random.default_rng(0).permutation(len(xy))
    ax.scatter(xy[order, 0], xy[order, 1], s=1.8, alpha=0.82, linewidths=0,
               c=[panel['palette'][panel['labels'][i]] for i in order], rasterized=False)
    low, high = xy.min(axis=0), xy.max(axis=0)
    center, half = (low + high) / 2, max(float(max(high - low)) * 0.54, 0.5e-6)
    ax.set(xlim=(center[0]-half, center[0]+half), ylim=(center[1]-half, center[1]+half))
    ax.set_aspect('equal', adjustable='box')
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(textwrap.fill(panel['title'], 38), fontsize=9)
    for spine in ax.spines.values():
        spine.set_color('#9a9a9a'); spine.set_linewidth(0.65)
    handles = [Line2D([], [], color=panel['palette'][c], marker='o', linestyle='', markersize=4,
                      label=textwrap.fill(c, 24)) for c in panel.get('legend_categories', panel['categories'])]
    return ax.legend(handles=handles, loc='center left', bbox_to_anchor=(1.03, 0.5),
                     ncol=1, frameon=False, fontsize=7)


def image_info(path, expected=None):
    from PIL import Image
    with Image.open(path) as img:
        pixels = list(img.size)
        img.verify()
    if expected is not None and pixels != list(expected):
        raise ValueError('unexpected image dimensions: %s: %s' % (path, pixels))
    return pixels


def write_tsv(path, rows, columns):
    with Path(path).open('w', encoding='utf-8', newline='') as sink:
        writer = csv.DictWriter(sink, fieldnames=columns, delimiter='\t', lineterminator='\n', extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)


def render_groups(directory, groups):
    import matplotlib as mpl
    mpl.use('Agg')
    import matplotlib.pyplot as plt
    from collections import Counter
    from embedding_plot import save_embedding
    panels, figures, composition = [], [], []
    (directory / 'single_panels').mkdir()
    # Three columns/rows per page bound canvas memory. Every panel has its own
    # source palette/legend, so cross-model cluster numbers imply no equivalence.
    for group_name, rows in groups.items():
        expanded = []
        for row in rows:
            views = []
            for panel in row:
                chunks, current, lines = [], [], 0
                for category in panel['categories']:
                    size = len(textwrap.wrap(category, 24)) or 1
                    if current and lines + size > 18:
                        chunks.append(current); current, lines = [], 0
                    current.append(category); lines += size
                if current:
                    chunks.append(current)
                for page, chunk in enumerate(chunks):
                    view = dict(panel, legend_categories=chunk, legend_page=page + 1)
                    if len(chunks) > 1:
                        view['title'] += '\nlegend %d/%d (all cells)' % (page + 1, len(chunks))
                    views.append(view)
            expanded.append(views)
        rows = expanded
        ncols = max(map(len, rows))
        for row_start in range(0, len(rows), 3):
            for col_start in range(0, ncols, 3):
                subset = [row[col_start:col_start+3] for row in rows[row_start:row_start+3]]
                nr, nc = len(subset), max(map(len, subset))
                if not nc:
                    continue
                width, height = 5.6 * nc, 5.0 * nr
                fig = plt.figure(figsize=(width, height))
                page_panels = []
                try:
                    for r, row in enumerate(subset):
                        for c, panel in enumerate(row):
                            ax = fig.add_axes([(c*5.6+0.3)/width, (height-(r+1)*5+0.6)/height, 3.0/width, 3.0/height])
                            legend = draw(ax, panel)
                            fig.canvas.draw()
                            box = legend.get_window_extent(fig.canvas.get_renderer())
                            bounds = fig.bbox
                            if box.y0 < 0 or box.y1 > bounds.height or box.x1 > (c+1)*5.6/width*bounds.width:
                                raise ValueError('single-column atlas legend does not fit; source category labels need a separate delivery page')
                            name = safe_name(group_name + '_' + panel['model'] + '_' + panel['basis'] + '_' + panel['column'] + '_legend%d' % panel['legend_page']) + '.png'
                            single = directory / 'single_panels' / name
                            one, axis = plt.subplots(figsize=(8, 8))
                            try:
                                draw(axis, panel)
                                save_embedding(one, single)
                            finally:
                                plt.close(one)
                            image_info(single, (2400, 2400))
                            entry = {k: v for k, v in panel.items() if k not in ('xy', 'ids', 'labels')}
                            entry.update(cells=len(panel['ids']), single_png='single_panels/' + name,
                                         panel=len(panels) + 1, cell_set_sha256=fingerprint(sorted(panel['ids'])))
                            panels.append(entry); page_panels.append(entry['panel'])
                            counts = Counter(panel['labels'])
                            for category in panel['categories']:
                                composition.append({'route': panel['route'], 'model': panel['model'],
                                    'panel': entry['panel'], 'column': panel['column'], 'category': category,
                                    'cells': counts[category], 'fraction': counts[category]/len(panel['ids']),
                                    'annotation_status': panel['annotation_status']})
                    prefix = '%s_r%d_c%d' % (group_name, row_start+1, col_start+1)
                    files = []
                    with mpl.rc_context({'savefig.bbox': None}):
                        for suffix, dpi in (('.png', 600), ('.pdf', 600), ('_preview.png', 100)):
                            path = directory / (prefix + suffix)
                            fig.savefig(path, dpi=dpi, bbox_inches=None, facecolor='white')
                            if path.suffix == '.png':
                                image_info(path, (int(width*dpi), int(height*dpi)))
                            elif path.read_bytes()[:5] != b'%PDF-':
                                raise ValueError('invalid PDF export')
                            files.append(path.name)
                    figures.append({'group': group_name, 'files': files, 'panels': page_panels,
                                    'inches': [width, height], 'dpi': 600, 'rows': nr, 'columns': nc})
                finally:
                    plt.close(fig)
    return panels, figures, composition


def run(root, run_id):
    root = Path(root).resolve()
    run_dir = root / '.workflow/runs' / run_id
    plan_path = run_dir / 'plan.json'
    plan = read_json(plan_path)
    item = next(x for x in plan['tasks'] if x['id'] == 'figures_comparison')
    spec = item['parameters']
    identity = {key: plan[key] for key in ('run_id', 'input_signature', 'code_signature')}
    from figures_comparison_evidence import plan_digest
    identity.update(task='figures_comparison', plan_sha256=plan_digest(plan_path))
    result = Path(plan['result_dir'])
    result.mkdir(parents=True, exist_ok=True)
    output = result / 'figures_comparison'
    task_dir = run_dir / 'tasks/figures_comparison'
    task_dir.mkdir(parents=True, exist_ok=True)
    with (result / '.figures_comparison.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another figure delivery publisher holds the run lock')
        sources = Sources(root, plan, spec)
        if output.exists():
            data = validate_manifest(output / 'delivery_manifest.json', identity)
            # Recovery must revalidate source bytes, not just old artifact hashes.
            for value in data['sources']:
                path = Path(value['path'])
                if str(path.resolve()) != value['resolved_path'] or sha(path) != value['sha256']:
                    raise ValueError('cannot resume delivery with changed sources: %s' % path)
            write_json(task_dir / 'task_outputs.json', delivery_record(output / 'delivery_manifest.json', identity))
            return output
        attempt = result / ('figures_comparison.attempt-' + uuid.uuid4().hex)
        attempt.mkdir()
        try:
            groups, coverage, dmr_files = build_specs(root, plan, spec, sources)
            panels, figures, composition = render_groups(attempt, groups)
            for entry in dmr_files:
                target = attempt / entry['target']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry['path'], target)
                image_info(target)
            write_tsv(attempt / 'route_coverage.tsv', coverage, ['route', 'selected', 'status', 'entries', 'reason'])
            write_tsv(attempt / 'panel_composition.tsv', composition,
                      ['route', 'model', 'panel', 'annotation_status', 'column', 'category', 'cells', 'fraction'])
            sources.verify()
            write_tsv(attempt / 'source_index.tsv', list(sources.records.values()),
                      ['path', 'resolved_path', 'source_task', 'run_id', 'task_id', 'kind', 'bytes', 'sha256', 'input_signature', 'code_signature'])
            text = '# Batch figure delivery / 同批次图集\n\n'
            text += 'Existing coordinates and annotations only; no analysis rerun.\n\n'
            text += 'Automatic file verification passed. Visual review is recorded separately and may still be pending.\n\n'
            for row in coverage:
                text += '- %s: %s (%s)\n' % (row['route'], row['status'], row['reason'] or str(row['entries']))
            text += '\nOrdinary and label-guided layouts are separate. Cluster numbers are model-local.\n'
            text += 'DMR files are original raster heatmap copies, not newly calculated or vector exports.\n'
            (attempt / 'README.md').write_text(text, encoding='utf-8')
            artifacts = [{'path': str(path.relative_to(attempt)), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                         for path in sorted(attempt.rglob('*')) if path.is_file()]
            manifest = dict(identity, schema_version=1, status='rendered_verified',
                created_at=datetime.now(timezone.utc).isoformat(), host=socket.gethostname(),
                slurm_job_id=os.environ.get('SLURM_JOB_ID'), presentation_only=True,
                analysis_rerun=False, coordinates_recomputed=False,
                contains_supervised_layouts=any('_supervised' in x['group'] for x in figures),
                expected_models=spec['models'], parameters=spec, route_coverage=coverage,
                sources=list(sources.records.values()), artifacts=artifacts, panels=panels, figures=figures,
                dmr_files=[{k: str(v) for k, v in x.items()} for x in dmr_files],
                model_cell_sets={row[0]['model']: {'cells': len(row[0]['ids']),
                    'sha256': fingerprint(sorted(row[0]['ids']))} for rows in groups.values() for row in rows},
                biological_quality_review='Not implied by presentation assembly')
            write_json(attempt / 'delivery_manifest.json', manifest)
            validate_manifest(attempt / 'delivery_manifest.json', identity)
            sources.verify()
            if output.exists():
                raise ValueError('refuse to replace an existing delivery')
            attempt.rename(output)
            write_json(task_dir / 'task_outputs.json', delivery_record(output / 'delivery_manifest.json', identity))
            return output
        except Exception as exc:
            write_json(task_dir / 'delivery_failure.json', {'attempt': str(attempt), 'error': str(exc),
                        'at': datetime.now(timezone.utc).isoformat()})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if not submit_host_execution_allowed(args.run_id):
        raise WorkflowError(login_host_refusal('render batch figure delivery'))
    if '/' in args.run_id or args.run_id in ('', '.', '..'):
        raise ValueError('invalid run ID')
    print(run(args.project, args.run_id))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, WorkflowError) as exc:
        print('ERROR: %s' % exc, file=sys.stderr)
        raise SystemExit(2)
