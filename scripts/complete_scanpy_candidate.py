#!/usr/bin/env python3
"""Apply evidence-bound candidate labels to saved cells without rerunning analysis.

Use prepare_scanpy_candidate_reference.py first. This producer writes a derived
H5AD, marker dotplot and tables; render_embedding_revision.py consumes its H5AD
as a dependent task. Neither step grants annotation approval.
"""
import argparse
import json
from pathlib import Path
import sys


def align_proposals(obs, table, placeholders):
    """Require exactly the source cells and their original cluster membership."""
    if not obs.index.is_unique or not table.index.is_unique:
        raise ValueError('Duplicate cell IDs')
    if set(obs.index) != set(table.index):
        raise ValueError('Proposal cell set differs from the saved analysis')
    table = table.loc[obs.index]
    if not (obs['leiden'].astype(str).values == table['leiden'].astype(str).values).all():
        raise ValueError('Proposal cluster membership differs from the saved analysis')
    for col in ('cell_type', 'confidence', 'marker_evidence'):
        if table[col].isna().any() or table[col].astype(str).str.strip().eq('').any():
            raise ValueError('Missing proposal ' + col)
    if table['cell_type'].str.strip().str.lower().isin(placeholders).any():
        raise ValueError('Unfinished candidate labels')
    if not table['review_status'].eq('agent_proposed_unapproved').all():
        raise ValueError('Expected unapproved agent proposals')
    return table


def complete(project, source_run, reference_dir, panels_path, output, task_dir):
    from _common import host_role, sha256_file, write_json
    from figures_comparison_evidence import task_evidence
    from record_annotation_review import handoff_directory
    if host_role() == 'submit':
        raise ValueError('Run candidate completion in a compute allocation')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import scanpy as sc
    from verify_derived_inputs import read_h5ad_for_consumer
    root = Path(project).resolve()
    sys.path.insert(0, str(root / 'Scripts/Common'))
    from annotation import PLACEHOLDER_LABELS
    state = root / '.workflow/runs' / source_run
    plan = json.loads((state / 'plan.json').read_text())
    task = next(t for t in plan['tasks'] if t['id'] == 'scanpy')
    status = task_evidence(state, plan, task)
    result = handoff_directory(root, source_run)
    summary = json.loads((result / 'scanpy/completion_summary.json').read_text())
    paths = [Path(p) for p in summary['artifacts'] if str(p).endswith('.h5ad')]
    if len(paths) != 1:
        raise ValueError('Expected one source analysis H5AD')
    source = paths[0]
    declared = []
    for p in status['outputs']:
        if Path(p).name == 'task_outputs.json':
            declared.extend(json.loads(Path(p).read_text())['artifacts'])
    if source.resolve() not in {Path(p).resolve() for p in declared}:
        raise ValueError('Source H5AD is not declared by its producer')
    reference = Path(reference_dir)
    provenance = json.loads((reference / 'provenance.json').read_text())
    if provenance['source_run'] != source_run or provenance['analysis_signature'] != summary['analysis_signature']:
        raise ValueError('Reference belongs to a different source analysis')
    for p, digest in provenance['sources'].items():
        if sha256_file(p) != digest:
            raise ValueError('Changed annotation source: ' + p)
    for record in provenance['artifacts']:
        if sha256_file(reference / record['path']) != record['sha256']:
            raise ValueError('Changed candidate reference')
    source_hash = sha256_file(source)
    a = read_h5ad_for_consumer(source)
    table = pd.read_csv(reference / 'cell_annotations.tsv', sep='\t', dtype=str, keep_default_na=False).set_index('cell_id')
    table = align_proposals(a.obs, table, PLACEHOLDER_LABELS)
    settings = json.loads(Path(panels_path).read_text())
    order = settings['cell_type_order']; palette = settings['palette']; panels = settings['dotplot_markers']
    if len(order) != len(set(order)) or set(order) != set(table.cell_type) or set(order) != set(panels) or len(order) != len(palette):
        raise ValueError('Panel, label, order and palette mismatch')
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Choose a new output revision')
    out.mkdir(parents=True, exist_ok=True)
    before = {k: np.array(v, copy=True) for k, v in a.obsm.items()}
    a.obs['candidate_cell_type'] = pd.Categorical(table.cell_type, categories=order, ordered=True)
    a.obs['annotation_confidence'] = pd.Categorical(table.confidence)
    a.obs['annotation_alternatives'] = table.alternatives.values
    a.obs['annotation_evidence'] = table.marker_evidence.values
    a.obs['annotation_review_status'] = 'agent_proposed_unapproved'
    a.uns['candidate_cell_type_colors'] = palette
    a.uns['candidate_cell_type_display_order'] = order
    a.uns['candidate_cell_type_display_palette'] = palette
    a.uns['annotation_status'] = 'candidate_auto_annotated_requires_review'
    a.uns['annotation_reference_independent'] = False
    a.uns['candidate_annotation_source_run'] = source_run
    # Preserve all saved coordinates, graphs, counts, raw expression and cells.
    for k, v in before.items():
        np.testing.assert_array_equal(a.obsm[k], v)
    derived = out / 'candidate_annotated.h5ad'
    a.write_h5ad(derived)
    a.obs.to_csv(out / 'cell_annotations.tsv', sep='\t', index_label='cell_id')
    table.reset_index().drop_duplicates('leiden').to_csv(out / 'cluster_proposals.tsv', sep='\t', index=False)
    missing = {label: [g for g in genes if g not in a.raw.var_names] for label, genes in panels.items()}
    panels = {label: [g for g in genes if g in a.raw.var_names] for label, genes in panels.items()}
    if any(not genes for genes in panels.values()):
        raise ValueError('A marker group has no genes in raw expression')
    dot = sc.pl.dotplot(a, panels, groupby='candidate_cell_type', use_raw=True,
        categories_order=order, expression_cutoff=0, standard_scale=None,
        title=None, return_fig=True,
        figsize=(max(15, sum(map(len, panels.values())) * .25), max(6, len(order) * .32)))
    dot.make_figure()
    dot.fig.canvas.draw()
    top = dot.fig.get_tightbbox(dot.fig.canvas.get_renderer()).y1 / dot.fig.get_figheight()
    dot.fig.text(.5, top + .04, 'Candidate annotation — awaiting user approval',
                 ha='center', va='bottom', fontsize=12)
    dot.fig.savefig(out / 'candidate_annotation_marker_dotplot.png', dpi=300, bbox_inches='tight')
    dot.dot_color_df.to_csv(out / 'marker_mean_log_expression.tsv', sep='\t')
    dot.dot_size_df.to_csv(out / 'marker_fraction_expressing.tsv', sep='\t')
    plt.close('all')
    for group in ('cohort', 'condition'):
        if group in a.obs:
            counts = pd.crosstab(a.obs[group], a.obs.candidate_cell_type)
            counts.to_csv(out / (group + '_cell_counts.tsv'), sep='\t')
            counts.div(counts.sum(axis=1), axis=0).to_csv(out / (group + '_cell_fractions.tsv'), sep='\t')
    if sha256_file(source) != source_hash:
        raise ValueError('Source changed during completion')
    write_json(out / 'candidate_delivery.json', dict(
        figure_format_policy='png_only',
        source_h5ad=str(source), source_sha256=source_hash, source_run=source_run,
        analysis_signature=summary['analysis_signature'], cells=a.n_obs,
        clusters=int(a.obs.leiden.nunique()), placeholder_cells=0,
        annotation_status='candidate_auto_annotated_requires_review', approval=False,
        coordinates_recomputed=False, source_unchanged=True,
        expression_scale='full-gene log-normalized raw; cutoff > 0; no gene-wise scaling',
        composition_denominator='retained cells within each sample or condition; descriptive',
        marker_settings_sha256=sha256_file(panels_path), missing_markers=missing,
        derived_h5ad_sha256=sha256_file(derived), visual_review='pending'))
    write_json(Path(task_dir) / 'task_outputs.json', {'artifacts': [str(p.resolve()) for p in out.iterdir() if p.is_file()]})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('project', 'source-run', 'reference-dir', 'panels', 'output', 'task-dir'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    complete(args.project, args.source_run, args.reference_dir, args.panels, args.output, args.task_dir)
