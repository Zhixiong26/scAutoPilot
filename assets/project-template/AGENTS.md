# Analysis results and figures

These rules cover all analysis in this project: skill workflows, custom tasks,
notebooks, exploratory scripts, parameter comparisons and figure-only revisions.

## Result ownership

Write new results under `Results/runs/<category>/<run-id>/`. Categories are
`scanpy`, `methscan`, `vmrseq`, `allcools`, `methylvi`, `multiomics`, `benchmark`
and `methylation_qc`. Classify by the final analysis: MethylVI on MethSCAn/vmrseq
features belongs to `methylvi`; a benchmark belongs to `benchmark`. Exploration
and recovery stay in the method category. Avoid new flat run directories.

Use the maintained planners (`plan_custom_workflow.py --category ...` for custom
DAGs) and the plan's `{result_dir}` in output arguments. For standalone work use
`tools/reserve_results.py --project . --category CATEGORY --run-id NEW_ID` and pass
its returned path to the script. Never claim reservation as execution evidence.
Keep run IDs unique; read old paths from their original plans/manifests.
Do not move historical results or edit active/frozen runtimes during maintenance.
Update `Results/RESULTS_INDEX.md` with verified paths, parameters and status.

## Figure contract, including exploration

Full RNA handoff includes an integrated A–K main PNG: cell types, Leiden, samples,
condition, confidence and three QC views; composition by condition/sample; and
a marker dotplot. Use three evidence-supported genes per displayed annotation,
export their mapping and mean/fraction tables, group related subtypes and keep
each name on one line. Record the annotation level; major-type merging is an
explicit annotation revision and state markers do not establish lineage.
Missing panels or insufficient marker evidence must be reported, never padded
with invented values. See the skill `references/rna-overview.md`. Bind the main
manifest using `audit_delivery.py --overview-manifest` or project
`config/figure_delivery.json`; a three-UMAP atlas alone is not the full RNA handoff.

Read the project-local scautopilot `references/publication-figures.md` and
`references/result-layout.md` when available. These requirements also apply when
the skill was not explicitly invoked:

- Individual embeddings use `Scripts/Common/embedding_plot.py:save_embedding()`:
  8×8 inch, 300 dpi, 2400×2400 PNG only; square axes with equal data
  aspect, outside single-column categorical legend or vertical numerical bar,
  no tight cropping. The helper may be imported by temporary scripts.
- Dotplots/heatmaps/comparison canvases use an appropriate layout; do not force
  them square. Export final PNGs only, including standard individual panels.
  Do not generate PDF/SVG, preview/review image duplicates, thumbnails or
  preview-only contact sheets. Inspect final PNGs directly.
- Pure appearance edits may directly overwrite requested figures without a new
  revision directory or another approval. Typography, legend grouping/order,
  wrapping, spacing, colours and point styling may change; preserve coordinates,
  cells, measurements, cluster membership and biological label meaning. Verify
  temporary renders before replacement and refresh affected manifests, artifact
  checksums, visual review and index links. Wait for any active writer.
  Data or scientific/annotation changes require a new result revision.
- Preserve unrequested display settings for plot-only edits. Keep gene scales,
  missingness, denominators and support counts
  explicit and export the numerical source tables.
- DMR heatmaps require raw mean ratio, DMR-wise Z-score, display-compressed
  Z-score and mean of saved single-cell Z-scores, with missing coverage retained;
  do not substitute Z-scored type means for the fourth view.
- Save source/settings/hashes and figure artifacts in a manifest. Inspect images
  for clipping, overlapping text, missing labels and palette consistency; record
  visual review separately from successful rendering. Mark unchecked candidates
  honestly; exploration is not an exemption from figure standards.

Production jobs use the scheduler-aware signed DAG and task output evidence.
Before a full-analysis handoff, run `tools/audit_delivery.py` with the requested
routes and every additional promised artifact (`--require`). Custom DAG success
does not waive formal comparison, workflow summary or fresh visual review.
See the skill's `references/delivery-audit.md`; report incomplete checks honestly.
Read the installed/project-local scautopilot skill for execution and recovery;
do not bypass compute-node execution guards or substitute wrappers for completion.

## External RNA reference annotation

For expression-based annotation of existing RNA clusters, follow the skill
`references/rna-reference-correlation.md`: query-cluster versus reference-type
mean log1p(CP10K) profiles, Spearman correlation, marker evidence, alternatives
and confidence. Per-cell kNN requires explicit selection and is not a prerequisite.
Preserve exact cells, clusters, scientific arrays and saved embeddings. Deliver
numbered correlation heatmaps, A–K overview with three supported markers per
displayed annotation, comparison and source tables, PNG-only, FOR REVIEW.
Group requested label systems and all related figures under one newly planned
annotation run; link necessary independent producers from one canonical entry.
Register overviews and run delivery audits. Cleanup of superseded outputs needs
user authorization, dependency checks and a removal record; never silently remove
required upstream evidence or mutate frozen plans.
