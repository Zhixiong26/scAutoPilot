# Batch comparison delivery

Single-line cell-type names are the default: `analysis.figures_comparison.legend_single_line: true`
before standard planning (or `legend_single_line: true` in the custom comparison
task parameters). Atlas and individual panels preserve
source category order and use unwrapped legend labels; legends still must fit
the canvas. The shared helper defaults to `save_embedding(..., wrap_legend=False)`.
Explicit user-requested wrapping remains available via the boolean setting.

New plans enable `analysis.figures_comparison.enabled: true`. The DAG is analysis tasks → `figures_comparison` → final `workflow_summary`. Set the boolean to false before planning to retain the previous DAG. Do not add the task to a frozen or active plan.

All selected routes, including prerequisites, appear in `Results/runs/<category>/<run-id>/figures_comparison/route_coverage.tsv`:

| Route | Existing data used |
|---|---|
| Scanpy | The run's declared h5ad; summary annotation_key (candidate versus reviewed), leiden, cohort, Harmony UMAP |
| MethSCAn VMR | Each threshold's embedding, coordinate table and cell filtering QC; annotation if present, leiden, sample_id |
| MethSCAn DMR | Checksum-verified copies of all four existing heatmaps: raw, Z-score, compressed Z-score, cell-type mean Z-score; explicit no-DMR outcomes |
| ALLCools | Native UMAP, manual_celltype, L1 and sample_id from the maximum feature target's clustered h5ad |
| MethylVI ALLCools | Ordinary and separately labelled supervised UMAPs across feature targets |
| MethylVI VMR | Threshold comparisons for each feature target |
| MethylVI VMR+DMR | Threshold comparisons for each feature target, preserving their route identity |

ALLCools feature subsets do not each have a newly computed native UMAP. DMR delivery collects original raster images and does not recompute heatmaps or claim vector originals. Candidate annotations remain candidates. VMR filtering can yield different cell sets across thresholds: each panel retains its own cells and records ID/coordinate hashes and cell counts.

Ordinary and label-guided layouts are separate. A supervised summary that legitimately skipped because fewer than two real labels exist produces an explicit not-applicable entry and preserves ordinary figures. A missing summary, missing planned weight or unexplained skip is an error. No training, UMAP calculation or raw ALLC reading is performed for delivery.

Each atlas provides one final 600 dpi PNG and individual 8×8 inch / 300 dpi PNGs through `embedding_plot.save_embedding`. Comparison canvases are an explicit exception to the square-canvas rule. Panels retain equal aspect, a single-column legend and no tight cropping. Pages contain at most three model rows and three columns; large legends split into labelled pages that retain all cells and colours. Every panel has its own source legend; equal cluster numbers in different models do not assert a shared cell identity.

Palette precedence is explicit `uns[column + '_display_order']` with `uns[column + '_display_palette']`, saved categorical `uns` colours, source run settings, then reconstruction using the source plotting rule in the declared Scanpy environment. Explicit display metadata is stored as parallel arrays so labels containing `/` are safe in HDF5. The manifest records the origin and version; it never labels a reconstructed palette as a stored original. MethSCAn's sorted-category tab20 rule is a fallback when no stored palette exists. Incomplete/duplicate display orders, uncovered labels and inconsistent saved palettes fail validation.

`panel_composition.tsv` has panel-specific counts and fractions. `source_index.tsv` records logical/resolved paths, checksums and source task/run identity. `delivery_manifest.json` records the signed plan, model list, parameters, annotation status, palette, coordinates, cell sets and checksums of every delivered artifact. `task_outputs.json` binds the manifest digest and the complete file set. Inspecting or resuming a run validates these artifact hashes; missing or changed output cannot remain complete. Source derived-file hashes are rechecked during rendering and recovery, without rescanning the raw inputs.

The task checks valid evidence for all upstream analysis tasks, not global run completion. It uses the plotting environment and resource profile and respects the existing compute-node/standalone guard. It never requires its own completion evidence or the downstream summary.

## Recovery and explicit source reuse

Rendering takes an advisory per-run publisher lock and writes a unique sibling attempt directory. Verification precedes atomic publication. Locks release when the owning process exits. If publication succeeded but the task evidence write was interrupted, retry verifies the existing signed delivery and reconstructs the task output record without overwriting figures. A different signature or damaged published directory is refused and preserved. Inspect the failure record under the task directory; explicitly archive an invalid delivery before rebuilding it. Failed attempts remain available for diagnosis.

Default sources must resolve within this run. A deliberate cross-run link additionally requires `analysis.figures_comparison.source_runs.<current-task>: {run_id: <source-run>, task_id: <source-task>}` before planning. The source must have valid evidence under its own frozen plan and matching task parameters. This registers provenance for an already valid current task; it does not create a cached task or skip scientific work. Unregistered redirected links fail closed.

## Visual review

For additional publication panels, composition denominators, marker-expression
scales and DMR matrix audits, read [publication figures](publication-figures.md).
Those derived revisions preserve the original delivery. Collecting existing DMR
rasters does not perform the matrix audit or produce a balanced heatmap.

`run_summary.json` distinguishes `analysis_status`, `figure_delivery_status` and `visual_review_status`. The ordinary run `status` describes automatic DAG completion. `rendered_verified` means file verification, not visual or biological approval. Stage reports also show the run-level delivery state, separately from stage task counts.

After actually examining all final atlas/DMR PNGs and representative single panels, record the outcome:

```bash
python tools/record_figure_review.py --project . --run-id <run-id> \
  --status passed --reviewer '<reviewer>' --notes '<inspection findings>' \
  --inspected <atlas>.png single_panels/<panel>.png
```

Supply every final atlas and DMR PNG, plus at least one single panel when present. Use `failed` and describe problems if inspection fails. The tool requires valid task evidence and binds the review to the manifest and inspected file hashes. It stores `.workflow/runs/<run-id>/figure_review.json` separately from immutable figure artifacts. Changed artifacts invalidate the review. No record means pending; only passed means visual delivery complete. This review does not approve a cell-type annotation or biological conclusion.

## Upgrade

The new Python tools change code_signature and input_signature. Do not update runtime files in a project with active jobs. Upgrade only idle projects, then make a new run and obtain matching validation evidence. Old frozen plans and outputs are not retroactively rewritten or redrawn. Projects with legacy task_outputs and no figure delivery remain readable.
