#!/usr/bin/env python3
"""SeekGene method 2: explicit read-count diagnostics, never a doublet classifier.
Run within a signed project DAG; see references/methylation-reads-qc.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

SOURCE_URL = 'https://seeksoul.online/cloudplatform-doc/zh/document/General/Notebooks.src/scMethyl+RNA_Multi-omics_Doublet_Detection.html'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_table(path):
    return pd.read_csv(path, sep=',' if str(path).endswith('.csv') else '\t', dtype={'cell_id': str, 'barcode': str})

def unique(frame, key):
    if key not in frame or frame[key].isna().any() or frame[key].duplicated().any():
        raise ValueError('Missing or duplicate identity: ' + key)

def ranked_counts(frame, smoothing_fraction=0.1):
    unique(frame, 'cell_id')
    counts = pd.to_numeric(frame['reads_counts'], errors='raise')
    if not np.isfinite(counts).all() or (counts < 0).any() or (counts % 1 != 0).any():
        raise ValueError('Reads must be finite nonnegative integer counts')
    if not 0 < smoothing_fraction <= 1:
        raise ValueError('smoothing_fraction must be in (0, 1]')
    frame = frame.copy(); frame['reads_counts'] = counts
    frame = frame.sort_values(['reads_counts', 'cell_id'], ascending=[False, True]).reset_index(drop=True)
    frame['rank'] = np.arange(1, len(frame) + 1)
    frame['log2_reads_plus1'] = np.log2(frame.reads_counts + 1)
    frame['adjacent_relative_drop'] = (frame.reads_counts - frame.reads_counts.shift(-1)) / frame.reads_counts.replace(0, np.nan)
    window = max(1, int(len(frame) * smoothing_fraction))
    frame['drop_moving_average'] = frame.adjacent_relative_drop.rolling(window, center=True, min_periods=1).mean()
    frame['moving_average_window'] = window
    return frame

def classify(counts, thresholds):
    low, high = thresholds.get('low_reads'), thresholds.get('high_reads')
    for value in (low, high):
        if value is not None and (not np.isfinite(value) or value < 0):
            raise ValueError('Thresholds must be finite and nonnegative')
    if low is not None and high is not None and low >= high:
        raise ValueError('low_reads must be smaller than high_reads')
    out = pd.Series('not_assessed', index=counts.index)
    if low is not None or high is not None:
        out.loc[counts.notna()] = 'within_configured_bounds'
        if low is not None: out.loc[counts <= low] = 'low_reads_review'
        if high is not None: out.loc[counts >= high] = 'high_reads_review'
    return out

def save(fig, out, name):
    fig.savefig(out / (name + '.png'), dpi=170, bbox_inches='tight')
    plt.close(fig)

def main(spec_path, output):
    spec = json.loads(spec_path.read_text())
    if spec.get('schema_version') != 1: raise ValueError('Expected schema_version 1')
    output.mkdir(parents=True, exist_ok=False)
    hashes = {str(spec_path.resolve()): sha(spec_path)}
    def source(path):
        path = Path(path)
        if not path.is_absolute(): path = spec_path.parent / path
        path = path.resolve(); hashes[str(path)] = sha(path)
        expected = spec.get('source_sha256', {}).get(str(path))
        if expected is None or hashes[str(path)] != expected:
            raise ValueError('Unpinned or changed source: ' + str(path))
        return path
    meta = read_table(source(spec['metadata'])); unique(meta, 'cell_id')
    if meta.sample_id.isna().any(): raise ValueError('Missing sample_id')
    palette = json.loads(source(spec['palette']).read_text()) if spec.get('palette') else {}
    for label in sorted(meta.cell_type.dropna().unique()):
        if label not in palette:
            palette[label] = matplotlib.colors.to_hex(plt.get_cmap('tab20')(len(palette) % 20))
    palette['Unannotated'] = '#bdbdbd'
    reports, tables = [], []
    entries = spec['samples']; sample_ids = [e['sample_id'] for e in entries]
    if len(set(sample_ids)) != len(sample_ids): raise ValueError('Duplicate samples')
    if set(meta.sample_id) - set(sample_ids): raise ValueError('Metadata samples missing from spec')
    for entry in entries:
        sample = entry['sample_id']; selected = meta[meta.sample_id == sample]
        if not entry.get('reads_file'):
            reports.append(dict(sample_id=sample, status='missing_source', cohort_cells=len(selected), matched_cells=0))
            continue
        counts = read_table(source(entry['reads_file']))
        unique(counts, 'barcode')
        if entry.get('id_mapping'):
            mapping = read_table(source(entry['id_mapping']))
            unique(mapping, 'barcode'); unique(mapping, 'cell_id')
            counts = counts.merge(mapping[['barcode', 'cell_id']], on='barcode', how='left', validate='one_to_one')
            if counts.cell_id.isna().any(): raise ValueError('Incomplete explicit barcode mapping')
        else:
            prefix = entry['cell_id_prefix']
            counts['cell_id'] = prefix + counts.barcode.astype(str)
        foreign = set(counts.cell_id) & set(meta.loc[meta.sample_id != sample, 'cell_id'])
        if foreign: raise ValueError('Mapped cells cross sample boundaries')
        counts = ranked_counts(counts, spec.get('smoothing_fraction', 0.1))
        counts = counts.merge(selected[['cell_id', 'cell_type']], on='cell_id', how='left', validate='one_to_one')
        counts['in_cohort'] = counts.cell_type.notna(); counts['cell_type'] = counts.cell_type.fillna('Unannotated')
        counts['sample_id'] = sample
        counts['read_depth_review'] = classify(counts.reads_counts, entry.get('thresholds', {}))
        counts['count_semantics'] = entry['count_semantics']
        counts['group_scope'] = entry['group_scope']
        if not counts.in_cohort.any(): raise ValueError('No exact cell matches for ' + sample)
        tables.append(counts)
        reports.append(dict(sample_id=sample, status='available', cohort_cells=len(selected),
                            source_cells=len(counts), matched_cells=int(counts.in_cohort.sum()),
                            unannotated_source_cells=int((~counts.in_cohort).sum()),
                            median_reads=float(counts.reads_counts.median()),
                            high_reads_review=int((counts.read_depth_review == 'high_reads_review').sum()),
                            low_reads_review=int((counts.read_depth_review == 'low_reads_review').sum())))
        fig, axes = plt.subplots(1, 3, figsize=(18, 5), constrained_layout=True)
        for label, group in counts.groupby('cell_type', sort=False):
            axes[0].scatter(group['rank'], group.log2_reads_plus1, s=4, color=palette[label], rasterized=True)
        axes[0].set(xlabel='Rank (all vendor-filtered barcodes)', ylabel='log2(vendor filtered counts + 1)', title=sample + ': reads rank')
        axes[1].plot(counts['rank'], counts.adjacent_relative_drop, color='#bdbdbd', lw=.5, label='Adjacent relative drop')
        axes[1].plot(counts['rank'], counts.drop_moving_average, color='#d95f02', lw=1.2, label='Centered moving average')
        axes[1].set(xlabel='Rank', ylabel='(count[i] - count[i+1]) / count[i]', title='Adjacent change'); axes[1].legend(fontsize=8)
        axes[2].hist(counts.log2_reads_plus1, bins=min(60, max(1, len(counts))), color='#4477aa')
        axes[2].set(xlabel='log2(vendor filtered counts + 1)', ylabel='Barcodes', title='Read-count distribution')
        handles = [Line2D([], [], marker='o', linestyle='', color=palette[k], label=k, markersize=4) for k in palette if k in set(counts.cell_type)]
        fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(.5, -.02), ncol=3, fontsize=8)
        save(fig, output, sample + '_reads_diagnostics')
    if not tables: raise ValueError('No usable read-count sources')
    all_reads = pd.concat(tables, ignore_index=True); unique(all_reads, 'cell_id')
    all_reads.to_csv(output/'all_vendor_barcodes_reads.tsv.gz', sep='\t', index=False)
    evidence = meta.merge(all_reads.drop(columns=['sample_id', 'cell_type']), on='cell_id', how='left', validate='one_to_one')
    evidence['read_depth_review'] = evidence.read_depth_review.fillna('missing_reads')
    evidence.to_csv(output/'cohort_reads_evidence.tsv.gz', sep='\t', index=False)
    pd.DataFrame(reports).to_csv(output/'sample_readiness.tsv', sep='\t', index=False)
    xy_tables = []
    for embedding in spec.get('embeddings', []):
        xy = read_table(source(embedding['path'])); unique(xy, 'cell_id')
        xy = evidence.merge(xy[['cell_id'] + embedding['columns']], on='cell_id', how='left', validate='one_to_one')
        if xy[embedding['columns']].isna().any().any(): raise ValueError('Missing cohort embedding coordinates')
        xy_tables.append((embedding, xy))
    if xy_tables:
        fig, axes = plt.subplots(len(entries), len(xy_tables), figsize=(6*len(xy_tables), 4.8*len(entries)), squeeze=False, constrained_layout=True)
        for row, entry in enumerate(entries):
            sample = entry['sample_id']
            for col, (embedding, xy) in enumerate(xy_tables):
                ax = axes[row, col]; x, y = embedding['columns']
                ax.scatter(xy[x], xy[y], s=2, c='#e3e3e3', rasterized=True)
                sub = xy[(xy.sample_id == sample) & xy.reads_counts.notna()]
                if len(sub):
                    # Identical read metric and limits for both modalities within each sample.
                    sc = ax.scatter(sub[x], sub[y], c=sub.log2_reads_plus1, s=5, cmap='viridis', rasterized=True)
                    fig.colorbar(sc, ax=ax, label='log2(vendor filtered counts + 1)', shrink=.7)
                    high = sub[sub.read_depth_review == 'high_reads_review']
                    ax.scatter(high[x], high[y], s=35, facecolors='none', edgecolors='red', linewidths=.7)
                ax.set_title(sample + ' | ' + embedding['name'] + '\n' + (str(len(sub)) + ' matched cells' if len(sub) else 'Reads unavailable'))
                ax.set(xlabel='UMAP1', ylabel='UMAP2'); ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect('equal', adjustable='box')
        save(fig, output, 'reads_umap_by_sample')
        # Compact paired view, same cells, same normalization; missing values remain gray.
        fig, axes = plt.subplots(1, len(xy_tables), figsize=(7*len(xy_tables), 6), squeeze=False, constrained_layout=True)
        for ax, (embedding, xy) in zip(axes[0], xy_tables):
            x, y = embedding['columns']; sub = xy[xy.reads_counts.notna()]
            ax.scatter(xy[x], xy[y], s=3, c='#dddddd', rasterized=True)
            sc = ax.scatter(sub[x], sub[y], s=5, c=sub.log2_reads_plus1, cmap='viridis', rasterized=True)
            fig.colorbar(sc, ax=ax, label='log2(vendor filtered counts + 1)', shrink=.65)
            ax.set_title(embedding['name'] + '\n' + str(len(sub)) + ' with reads / ' + str(len(xy)) + ' paired cells')
            ax.set(xlabel='UMAP1', ylabel='UMAP2'); ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect('equal', adjustable='box')
        save(fig, output, 'reads_umap_comparison')
    if 'current_residual' in evidence:
        evidence.groupby(['sample_id', 'current_residual'], dropna=False).agg(cells=('cell_id', 'size'), reads_available=('reads_counts', 'count'), median_reads=('reads_counts', 'median')).to_csv(output/'residual_reads_summary.tsv', sep='\t')
    summary = dict(schema_version=1, method='SeekGene method 2: read-count diagnostics', source_url=SOURCE_URL,
        sources_sha256=hashes, cohort_cells=len(meta), cohort_with_reads=int(evidence.reads_counts.notna().sum()),
        missing_samples=[r['sample_id'] for r in reports if r['status']=='missing_source'],
        default_thresholds='none; not_assessed is not singlet', cells_removed=0, labels_changed=0,
        count_semantics='Source-defined filtered counts; read/pair and dedup status must be supplied or remain unknown',
        library_scope='Source grouping is explicit; sample is not assumed to be a capture library',
        smoothing='Centered moving average; not LOESS', figure_review_status='pending_visual_inspection')
    (output/'manifest.json').write_text(json.dumps(summary, indent=2))
    (output/'Report.md').write_text('# Methylation read-count diagnostics\n\n'+
        'Matched cohort cells: %d / %d. Missing samples: %s.\n\n' % (summary['cohort_with_reads'],len(meta),', '.join(summary['missing_samples']))+
        'Descending ranks and adjacent changes use all barcodes in each vendor-filtered file. UMAPs use the existing paired cohort only.\n\n'+
        'No default count cutoff, no fixed top-200 rule, no doublet calls or cell removal. Optional explicit per-source count thresholds produce review flags only. Missing reads remain NA. Vendor count read/pair and dedup semantics are unverified unless provided.\n\n'+
        'The smoothing line is a centered moving average, not LOESS. Histograms summarize the distribution without a KDE bandwidth assumption. Cell types are label-keyed.\n\nSource: '+SOURCE_URL+'\n')
    return [p for p in output.iterdir() if p.is_file()]

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--spec', type=Path, required=True); p.add_argument('--output', type=Path, required=True); p.add_argument('--task-dir', type=Path, required=True); a=p.parse_args()
    artifacts=main(a.spec.resolve(), a.output.resolve())
    a.task_dir.mkdir(parents=True, exist_ok=True)
    (a.task_dir/'task_outputs.json').write_text(json.dumps({'artifacts':[str(p) for p in artifacts]}, indent=2))
