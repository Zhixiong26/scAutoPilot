# Methylation read-count QC: SeekGene method 2

Use for explicit per-cell methylation read-depth diagnostics and potential
high-read review. Source: [SeekGene notebook, method 2](https://seeksoul.online/cloudplatform-doc/zh/document/General/Notebooks.src/scMethyl+RNA_Multi-omics_Doublet_Detection.html).
This complements the [paired-doublet policy](paired-doublets.md); it is not a
MethylScrublet implementation, doublet probability, or authorized exclusion list.

## Data and interpretation

Require a vendor `filtered_barcode_reads_counts.csv` with `barcode,reads_counts`
or an explicitly documented equivalent. Counts must be finite nonnegative
integers. Record whether they mean reads/pairs and pre/post-deduplication; leave
unknown semantics explicit. Do not use selected-bin CpG coverage as reads.

Use an explicit prefix for an established shared barcode identity (e.g. DD-MET5),
or a validated one-to-one `barcode,cell_id` mapping (e.g. DD-MET3). Never guess
barcode transformations from kit names. Reject duplicate, cross-sample or
unmapped identities. Annotations/coordinates require exact `cell_id` keys.
Sources may include barcodes outside the final cohort: retain them as unannotated
and report both populations. Missing sources remain missing, not zero/singlet.
A source group/sample is not automatically an independent capture library;
record `group_scope` and avoid pooled thresholds across libraries.

## Portable opt-in execution

Generated projects include `tools/run_methylation_reads_qc.py` and
`tools/plan_methylation_reads_qc.py`. The standard analysis routes are unchanged.
On an idle project, prepare JSON with:

```json
{
  "schema_version": 1,
  "metadata": "cohort.tsv.gz",
  "palette": "palette.json",
  "smoothing_fraction": 0.1,
  "samples": [
    {"sample_id": "sample_A", "reads_file": "counts.csv",
     "cell_id_prefix": "sample_A_",
     "count_semantics": "vendor filtered count; read/pair and dedup unknown",
     "group_scope": "source sample; capture identity unverified",
     "thresholds": {}},
    {"sample_id": "sample_B", "reads_file": null}
  ],
  "embeddings": [
    {"name": "Methylation", "path": "meth_xy.tsv.gz", "columns": ["UMAP1", "UMAP2"]},
    {"name": "RNA", "path": "rna_xy.tsv.gz", "columns": ["rna_umap1", "rna_umap2"]}
  ],
  "source_sha256": {"/resolved/path/to/every/input": "actual sha256"}
}
```

Metadata columns: `cell_id,sample_id,cell_type`; optional `current_residual`.
Palette maps label to color. `id_mapping` replaces `cell_id_prefix` when needed.
All actual input files, including palette and coordinate tables, require pinned
SHA-256 entries keyed by resolved absolute path. Relative inputs resolve beside
the original spec. Missing file declarations are explicit nulls.

```bash
python tools/plan_methylation_reads_qc.py --project /path/to/project \
  --spec /path/to/spec.json --run-id methylation-reads-qc-YYYYMMDD-01
```

Use configured stage Python and scheduler; optionally choose `--partition` from
site availability. The planner freezes runtime/config, validates quick/full,
creates a signed diagnostic + summary DAG, and submits through the standard
executor. Run calculations and plots on compute nodes. Do not invoke the worker
on a login node. For release smoke tests pass `--smoke-test` pointing to
`tests/test_methylation_reads_qc.py`; it becomes a prerequisite compute task.

## Outputs and review

Ranks cover all vendor-filtered barcodes per source, descending by count with
stable ID tie-breaking. Plot log2(count+1), adjacent relative count decrease,
and a centered moving average (default 10% window). Zero denominator and final
adjacent changes are NA. The tutorial calls its rolling average LOESS; label it
correctly here. Histogram replaces KDE to avoid a bandwidth assumption.

Produce source-level tables, cohort evidence, source/match readiness, per-sample
rank/distribution plots, paired UMAPs with shared limits for this same read metric,
and optional residual stratification. Missing UMAP values remain gray. No
clustering, labels, cohort membership or coordinates are recomputed.

Thresholds default to none (`not_assessed`). After biological/QC review one may
configure per-source `low_reads` and/or `high_reads`, with inclusive bounds;
these generate review flags only. Never copy the example's fixed top/bottom 200
or force a fixed doublet fraction. No automatic data filtering is implemented.
High reads need independent evidence; low reads indicate coverage QC, not a
doublet call. Store this evidence separately from the nine-column doublet table.
Inspect plots and record review evidence tied to artifact hashes before delivery.
