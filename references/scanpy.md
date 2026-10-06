# Scanpy and Harmony

The portable implementation accepts 10x directories, ZIP archives containing exactly one matrix, and 10x H5. It performs per-sample QC, optional Scrublet, concatenation, normalization, HVG, PCA, optional Harmony, neighbours, UMAP, Leiden, markers, and guarded annotation.

RNA cell IDs use explicit `cell_id_prefix`. Preserve raw counts in `layers['counts']` and log-normalized full-gene values in `raw`. An annotation profile is valid only when its analysis signature and expected cluster set match exactly.

## The first pass auto-annotates

A candidate run that ends at `Unassigned` is unfinished. It must provide a complete automatic proposal first; the user audits labels rather than performing the initial annotation.

Annotate by looking the markers up as they are. There is no bundled reference panel and no crosswalk to reuse: a label carried over from another project, from `Notebooks/example_ipf_scanpy.ipynb`, or from a fixed panel is exactly the transplant this workflow forbids. Establish each cluster's identity from its own ranked markers, its canonical lineage markers, and its QC and sample composition, and be able to say which genes carried the call.

1. Run the `scanpy` task as a candidate. If `annotation.table` supplies non-placeholder labels for every analysed cell, the notebook uses exact cell-ID matches to render a complete candidate UMAP and records each cluster's majority label, purity, competing labels, and ranked markers. This remains unreviewed evidence even if the input table is marked approved for another downstream purpose.
2. If no complete cell-level reference is available, read `candidate_annotation_audit.tsv`, the per-cluster marker figure, QC, and sample composition. Automatically assign the best-supported biological label to every cluster, looking up unfamiliar markers when needed. Record low confidence and alternatives instead of using `Unassigned`.
3. Write the proposed mapping and its confidence/evidence into a review worksheet or proposed profile, and write matching `markers.dotplot_markers` and `markers.cell_type_order` groups so the candidate annotation dotplot and legend use the same names.
4. Deliver the fully coloured candidate UMAP and ask the user to audit the proposals, naming low-confidence or mixed clusters and the evidence behind them. Candidate labels must never be described as user-approved.
5. After user approval or correction, record the reviewed mapping with `tools/record_annotation_review.py`, set the approval state, and re-run as `run_kind: baseline` with `analysis_confirmed: true`. Formal outputs then carry `cell_type`; only this reviewed baseline may feed cell-type DMR.

The profile you record is bound to this run's analysis signature and exact cluster set, so a later parameter change makes it stale and the run refuses it rather than reusing it silently. Cell-type DMR still never consumes an unreviewed table: `NA`, `Unassigned` and `requires_review` remain invalid there, which is why an uncalled cluster has to be resolved rather than parked.

`Notebooks/scanpy_workflow.ipynb` is the implementation, not a copy of one: the DAG's scanpy task runs `run_scanpy_notebook.py`, which writes a parameter sidecar and executes that same notebook through a kernel, so there is one code path rather than a notebook and a batch script that must be kept in step. `Scripts/Scanpy/README.md` documents the full ten-step notebook flow, the verification loop, and the completion standard; `Scripts/Scanpy/Report.md` is the bilingual evidence ledger. `Notebooks/example_ipf_scanpy.ipynb` is a shipped worked example that the DAG never executes — including its reviewed cluster-to-cell-type mapping, which is valid only for that example's exact cluster set and must not be transplanted.

## Figure standard

All intermediate, candidate, baseline and publication UMAPs use the shared `Scripts/Common/embedding_plot.py` helper. `save_embedding(figure, path)` exports an **8 × 8 in square canvas**, including its legend, at **300 dpi (2400 × 2400 px PNG)**. PDF/SVG use the same physical size. Never use `bbox_inches='tight'` for these exports: a tight crop changes the canvas shape. The helper overrides even a global `savefig.bbox='tight'` setting.

Single-panel axes remain 4 × 4 in; comparison figures fit smaller square panels into the same canvas (two panels are stacked at 3.04 × 3.04 in each; larger comparisons use a grid). Construction and export both use the shared `panel_positions()` rule; the notebook's `figure-standard` cell imports helpers, rather than defining another geometry. `square_panels()` first gives before/after views a common data window; the shared exporter preserves that window and equal aspect without stretching coordinates. Compare like-for-like single panels across rounds rather than a single plot to a smaller overview panel.

Categorical legends use **one vertical column on the right**, preserving colours and category order; long display labels wrap and crowded legends reduce font size. Continuous colour bars use **one vertical bar per numerical panel**, outside its square axes. If a comparison cannot fit readable keys, export its panels separately; do not silently add a second legend column or clip labels. Numeric Leiden labels placed on the data are unchanged. Dotplots, heatmaps and non-embedding QC charts retain content-appropriate layouts.

The same exporter is required in manually authored final/publication rendering helpers. Do not change scientific coordinates, clustering, labels or palettes just to achieve this layout. The shared Python source is part of `code_signature`; adopting it in an existing generated project requires a fresh plan and validation, not overwriting an in-flight run. Updating this skill does not retroactively redraw existing outputs.
