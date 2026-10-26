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

Read the project-local scautopilot `references/publication-figures.md` and
`references/result-layout.md` when available. These requirements also apply when
the skill was not explicitly invoked:

- Individual embeddings use `Scripts/Common/embedding_plot.py:save_embedding()`:
  8×8 inch, 300 dpi, 2400×2400 PNG and matching PDF; square axes with equal data
  aspect, outside single-column categorical legend or vertical numerical bar,
  no tight cropping. The helper may be imported by temporary scripts.
- Dotplots/heatmaps/comparison canvases use an appropriate layout; do not force
  them square. Export individual standard embedding panels alongside previews.
- Preserve saved coordinates, cells, labels, order and palette for plot-only
  revisions. Keep gene scales, missingness, denominators and support counts
  explicit and export the numerical source tables.
- DMR heatmaps require raw mean ratio, DMR-wise Z-score, display-compressed
  Z-score and mean of saved single-cell Z-scores, with missing coverage retained;
  do not substitute Z-scored type means for the fourth view.
- Save source/settings/hashes and figure artifacts in a manifest. Inspect images
  for clipping, overlapping text, missing labels and palette consistency; record
  visual review separately from successful rendering. Mark unchecked candidates
  honestly; exploration is not an exemption from figure standards.

Production jobs use the scheduler-aware signed DAG and task output evidence.
Read the installed/project-local scautopilot skill for execution and recovery;
do not bypass compute-node execution guards or substitute wrappers for completion.
