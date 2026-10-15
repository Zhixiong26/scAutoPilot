# MethSCAn, VMR, and DMR

The packaged workflow discovers indexed ALLCs independently for each `samples.tsv` row, applies the configured cell-ID rule and methylation context, then runs coverage conversion, prepare, filter, smooth, VMR scan/matrix, and Scanpy representation. Samples, thresholds, context, and chromosome order come from configuration and `chrom_sizes`; unmatched files are errors or explicit QC records, never silent skips.

Cell-type DMR requires `review_status: approved`, rejects case-insensitive placeholder labels and unresolved per-row review/eligibility flags, and enforces a minimum cell count. Per-sample and pooled-sample DMR are separate. Resume only comparisons whose identity, completion state, and format match.

Set `analysis.methscan.use_rna_annotation: false` to defer annotation entirely:
unsupervised VMR remains available, while cell-type DMR routes are disabled.
Selection records unavailable RNA annotation; VMR omits the corresponding color
panel and reports zero available annotations. Saved VMR H5ADs persist the display
order and palette used for each categorical panel, allowing comparison renders
to reuse the same colors. Explicit metadata supplies sample identity and barcode;
sample IDs containing underscores remain intact in both QC tables and embeddings.

Bind that approval to the actual table revision and check review flags/mixed
labels before the handoff; exact placeholder checks do not detect every uncertain
biological label. See [reviewed input handoff](iteration-practice.md#annotation-revisions-and-downstream-handoff).

`Scripts/Methscan/README.md` documents the stage sequence, output tree, and the `jobs × threads ≤ SLURM_CPUS_PER_TASK` constraint; `Scripts/Methscan/Report.md` is the bilingual evidence ledger. The `run_*.sbatch` wrappers and `submit_methscan_pipeline.sh` execute these stages standalone, sharing one dependency-chain implementation through `Scripts/Common/submit_helpers.sh`.

The heatmap branch may use raw-p fallback only for the known FDR division-by-zero failure. Top-N hypo-DMR heatmaps produce raw mean ratio, DMR-wise z-score, and display-compressed z-score figures. The MethylVI extension instead uses all pooled hypo-DMRs passing configured raw-p and absolute-difference thresholds, without Top-N truncation, and appends only zero-overlap DMRs to selected VMRs.

## Batch comparison

VMR atlas rows use each threshold’s retained cells and verify its own cell QC; they need not equal the pre-VMR filtered cell list. DMR delivery collects and hashes existing heatmaps with explicit zero-DMR outcomes, without reselection or matrix computation. See [batch delivery](figures-comparison.md).

For sparse or visually misleading heatmaps, audit saved matrix coverage,
normalization axes, DMR direction and group support before changing the display.
Missing coverage remains masked, not zero methylation. Balanced or aggregated
views are separate documented derivatives; see [heatmap audit](publication-figures.md#dmr-heatmaps-inspect-the-matrix-before-changing-the-display).
