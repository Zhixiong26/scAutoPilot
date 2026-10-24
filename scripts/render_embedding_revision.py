#!/usr/bin/env python3
"""Render a provenance-bound H5AD embedding revision through the shared geometry.

No PCA, graph, UMAP, clustering or annotation inference is performed here.
"""
import argparse
import json
from pathlib import Path
import sys


def render(project, spec_path, output, task_dir):
    from _common import host_role, WorkflowError, sha256_file, write_json
    if host_role() == 'submit':
        raise WorkflowError('Render on a compute allocation, not the submit host')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import scanpy as sc
    from PIL import Image
    from figures_comparison_evidence import task_evidence
    sys.path.insert(0, str(Path(project) / 'Scripts/Common'))
    from embedding_plot import save_embedding

    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    source = spec['source']
    path = Path(source['path']).resolve()
    if sha256_file(path) != source['sha256']:
        raise WorkflowError('Source H5AD SHA-256 mismatch')
    state = Path(source['run_dir'])
    plan = json.loads((state / 'plan.json').read_text())
    item = next(x for x in plan['tasks'] if x['id'] == source['task_id'])
    status = task_evidence(state, plan, item)
    # A valid producer task must actually declare this H5AD, not merely coexist.
    declared = []
    for record in status['outputs']:
        if Path(record).name == 'task_outputs.json':
            declared += json.loads(Path(record).read_text())['artifacts']
    if path not in {Path(x).resolve() for x in declared}:
        raise WorkflowError('Source H5AD is not an artifact of the declared task')
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise WorkflowError('Preserve existing delivery; select a new revision directory')
    out.mkdir(parents=True, exist_ok=True)
    from verify_derived_inputs import read_h5ad_for_consumer
    a = read_h5ad_for_consumer(path)
    if not a.obs_names.is_unique:
        raise WorkflowError('Duplicate cell IDs')
    coordinates = a.obsm['X_umap'].copy()
    if coordinates.shape != (a.n_obs, 2) or not np.isfinite(coordinates).all():
        raise WorkflowError('Invalid saved embedding')
    columns = spec['panels']
    keys = [x['key'] for x in columns]
    if len(keys) != len(set(keys)) or any(key not in a.obs for key in keys):
        raise WorkflowError('Duplicate or absent panel keys')
    table = a.obs[keys].copy()
    table[['UMAP1', 'UMAP2']] = coordinates
    table.to_csv(out / 'cell_embedding.tsv', sep='\t', index_label='cell_id')
    panels, composition = [], []
    for i, panel in enumerate(columns, 1):
        key = panel['key']
        kind = panel['kind']
        if kind not in {'categorical', 'continuous'}:
            raise WorkflowError('Unknown panel kind')
        palette_source = None
        if kind == 'categorical':
            if a.obs[key].isna().any():
                raise WorkflowError('Categorical panel contains missing labels: ' + key)
            if not isinstance(a.obs[key].dtype, pd.CategoricalDtype):
                a.obs[key] = pd.Categorical(a.obs[key])
            explicit_order = a.uns.get(key + '_display_order')
            explicit_palette = a.uns.get(key + '_display_palette')
            if explicit_order is not None or explicit_palette is not None:
                if explicit_order is None or explicit_palette is None:
                    raise WorkflowError('Incomplete display metadata')
                order, colors = list(map(str, explicit_order)), list(map(str, explicit_palette))
                if len(set(order)) != len(order) or set(order) != set(a.obs[key].cat.categories) or len(colors) != len(order):
                    raise WorkflowError('Invalid display order/palette')
                a.obs[key] = a.obs[key].cat.reorder_categories(order)
                a.uns[key + '_colors'] = colors
                palette_source = 'explicit_display_metadata'
            elif key + '_colors' in a.uns:
                if len(a.uns[key + '_colors']) != len(a.obs[key].cat.categories):
                    raise WorkflowError('Incomplete saved palette')
                palette_source = 'saved_categorical_colors'
            else:
                palette_source = 'reconstructed_scanpy_default_' + sc.__version__
        fig = sc.pl.umap(a, color=key, title=panel['title'], size=spec.get('point_size', 7),
                         show=False, return_fig=True, frameon=True)
        stem = 'panel_%02d' % i
        png, pdf, preview = [out / (stem + ext) for ext in ('.png', '.pdf', '_preview.png')]
        save_embedding(fig, png)
        save_embedding(fig, pdf)
        fig.canvas.draw()
        axes = [ax for ax in fig.axes if getattr(ax, '_colorbar', None) is None]
        if len(axes) != 1:
            raise WorkflowError('Individual embedding must contain one panel')
        ax = axes[0]
        box = ax.get_window_extent()
        xspan = abs(np.diff(ax.get_xlim())[0]); yspan = abs(np.diff(ax.get_ylim())[0])
        if not np.isclose(box.width, box.height) or not np.isclose(xspan, yspan):
            raise WorkflowError('Non-square or anisotropic embedding axes')
        with Image.open(png) as im:
            if im.size != (2400, 2400):
                raise WorkflowError('Embedding PNG must be 2400 by 2400')
            im.thumbnail((800, 800)); im.save(preview)
        record = dict(key=key, title=panel['title'], kind=kind, png=png.name, pdf=pdf.name,
                      preview=preview.name, canvas_inches=[8, 8], png_pixels=[2400, 2400],
                      axes_inches=[box.width / fig.dpi, box.height / fig.dpi],
                      equal_data_units=True, palette_source=palette_source,
                      scatter_rasterized=[bool(c.get_rasterized()) for c in ax.collections])
        if kind == 'categorical':
            legend = ax.get_legend()
            if legend is None:
                raise WorkflowError('Missing categorical legend')
            ncol = getattr(legend, '_ncols', getattr(legend, '_ncol', 1))
            lb = legend.get_window_extent(fig.canvas.get_renderer())
            if ncol != 1 or lb.x0 < box.x1 or lb.x1 > fig.bbox.width or lb.y0 < 0 or lb.y1 > fig.bbox.height:
                raise WorkflowError('Legend is not a readable external single column')
            record['order'] = list(map(str, a.obs[key].cat.categories))
            record['palette'] = list(map(str, a.uns[key + '_colors']))
            for value, n in a.obs[key].value_counts(sort=False).items():
                composition.append(dict(panel=key, category=str(value), cells=int(n),
                                        denominator=a.n_obs, fraction=float(n / a.n_obs)))
        else:
            bars = [axis._colorbar for axis in fig.axes if getattr(axis, '_colorbar', None)]
            if len(bars) != 1 or bars[0].orientation != 'vertical':
                raise WorkflowError('Continuous panel must use an external vertical colorbar')
        panels.append(record); plt.close(fig)
    np.testing.assert_array_equal(a.obsm['X_umap'], coordinates)
    if sha256_file(path) != source['sha256']:
        raise WorkflowError('Source changed during rendering')
    pd.DataFrame(composition).to_csv(out / 'panel_composition.tsv', sep='\t', index=False)
    # Preview contact sheet preserves every individual panel's geometry/legend.
    cols = 2; rows = (len(panels) + 1) // 2
    sheet = Image.new('RGB', (800 * cols, 800 * rows), 'white')
    for i, panel in enumerate(panels):
        with Image.open(out / panel['preview']) as im:
            sheet.paste(im.convert('RGB'), ((i % cols) * 800, (i // cols) * 800))
    sheet.save(out / 'overview_preview.png')
    lines = ['# Embedding figure revision', '', spec['description'], '',
             'Saved coordinates and cell membership are unchanged. Candidate labels remain candidates.', '',
             '| Panel | PNG | PDF |', '|---|---|---|']
    lines += ['| %s | [PNG](%s) | [PDF](%s) |' % (p['title'], p['png'], p['pdf']) for p in panels]
    (out / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    artifacts = [dict(path=f.name, bytes=f.stat().st_size, sha256=sha256_file(f))
                 for f in sorted(out.iterdir()) if f.is_file()]
    manifest = dict(status='rendered_verified', presentation_only=True, analysis_rerun=False,
                    coordinates_recomputed=False, source=source,
                    source_input_signature=plan['input_signature'], source_code_signature=plan['code_signature'],
                    settings_sha256=sha256_file(spec_path), cells=a.n_obs,
                    annotation_status=spec['annotation_status'], panels=panels, artifacts=artifacts,
                    visual_review='pending_separate_hash_bound_record')
    write_json(out / 'delivery_manifest.json', manifest)
    write_json(Path(task_dir) / 'task_outputs.json',
               {'artifacts': [str(f.resolve()) for f in sorted(out.iterdir()) if f.is_file()]})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'spec', 'output', 'task-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    render(args.project, args.spec, args.output, args.task_dir)
