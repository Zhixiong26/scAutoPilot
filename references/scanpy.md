# Scanpy and Harmony

The portable implementation accepts 10x directories, ZIP archives containing exactly one matrix, and 10x H5. Its legacy notebook performs per-sample QC, optional Scrublet, concatenation, normalization, HVG, PCA, optional Harmony, neighbours, UMAP, Leiden, markers, and guarded annotation. For new paired analyses follow [paired doublets](paired-doublets.md): compare Scrublet versus scDblFinder on identical per-capture inputs, select one RNA method, then reconcile with MethylScrublet before unified filtering. The legacy Scrublet path alone does not implement this policy and must not remove cells before DNAm scoring.

RNA cell IDs use explicit `cell_id_prefix`. Preserve raw counts in `layers['counts']` and log-normalized full-gene values in `raw`. An annotation profile is valid only when its analysis signature and expected cluster set match exactly.

## The first pass auto-annotates

A candidate run that ends at `Unassigned` is unfinished. It must provide a complete automatic proposal first; the user audits labels rather than performing the initial annotation.

The notebook is the numerical producer, not a biological reasoning service.
Without a complete reference or evidence-derived panels it saves marker/QC
evidence with `candidate_annotation_incomplete`. It suppresses the placeholder
cell-type UMAP; comparison delivery then contains cluster/sample diagnostics.
The agent must continue from this checkpoint, rather than waiting for the user
to supply labels or presenting computational completion as delivery completion.
This is not an annotation-approval gate: render the full proposal first and label
the delivery “awaiting user approval”. Low-confidence lineage/state proposals
include alternatives and evidence; do not manufacture a precise subtype.

Annotate by looking the markers up as they are. There is no bundled reference panel and no crosswalk to reuse: a label carried over from another project, from `Notebooks/example_ipf_scanpy.ipynb`, or from a fixed panel is exactly the transplant this workflow forbids. Establish each cluster's identity from its own ranked markers, its canonical lineage markers, and its QC and sample composition, and be able to say which genes carried the call.

1. Run the `scanpy` task as a candidate. If `annotation.table` supplies non-placeholder labels for every analysed cell, the notebook uses exact cell-ID matches to render a complete candidate UMAP and records each cluster's majority label, purity, competing labels, and ranked markers. This remains unreviewed evidence even if the input table is marked approved for another downstream purpose.
2. If no complete cell-level reference is available, read `candidate_annotation_audit.tsv`, the per-cluster marker figure, QC, and sample composition. Automatically assign the best-supported biological label to every cluster, looking up unfamiliar markers when needed. Record low confidence and alternatives instead of using `Unassigned`.
3. Write the proposed mapping and its confidence/evidence into a review worksheet or proposed profile, and write matching `markers.dotplot_markers` and `markers.cell_type_order` groups so the candidate annotation dotplot and legend use the same names.
4. Deliver the fully coloured candidate UMAP and ask the user to audit the proposals, naming low-confidence or mixed clusters and the evidence behind them. Candidate labels must never be described as user-approved.
5. After user approval or correction, bind approval to the exact annotation revision and exported cells, and record the reviewed cluster mapping with `tools/record_annotation_review.py`. A requested baseline rerun uses a new run ID, `run_kind: baseline` and `analysis_confirmed: true`; verify its actual partition before applying the mapping. A rerun is optional when the verified, explicitly approved derived cell table is the intended downstream input. See [handoff and review flags](iteration-practice.md#annotation-revisions-and-downstream-handoff) before enabling cell-type DMR.

The profile is bound to this run's analysis signature and exact cluster set. Changes to signature-covered analysis parameters make it stale. Plumbing fields (`run_kind`, `iteration_id`, `analysis_confirmed`) are excluded from that signature; identical signatures and cluster numbers alone cannot prove identical cell membership after a numerical rerun. Cell-type DMR never consumes an unreviewed table: resolve low-confidence/mixed groups explicitly, retaining an inclusion/exclusion ledger for any derived DMR input.

## Candidate reference tool

After completing this run's marker review, write a worksheet with `cluster`,
`cell_type`, `confidence`, `alternatives`, and `evidence` columns. Every observed
cluster needs one non-placeholder label and nonempty confidence/evidence. Then:

```bash
"$PYTHON" "$PROJECT/tools/prepare_scanpy_candidate_reference.py" \
  --project "$PROJECT" --run-id candidate-000 \
  --worksheet "$PROJECT/config/candidate-000-proposals.tsv" \
  --output-dir Data/Annotation/candidate-000-proposals
```

The tool writes `cell_annotations.tsv` and `provenance.json` in a new directory,
preserving cell order and marking all labels `agent_proposed_unapproved`. It
checks source task evidence and exact cluster coverage, keeps marker evidence
and records input/output hashes. It neither edits project configuration nor
approves a mapping. If selected as a later candidate's reference, declare the
table through `annotation.table` with `review_status: pending`; the notebook
matches cell IDs and measures disagreement against the new partition. Such a
reference is dependent evidence and cannot validate itself.

### Complete a saved candidate without numerical replay

After exporting the reference, plan a custom DAG with two tasks:

1. `complete_scanpy_candidate.py --project PROJECT --source-run SOURCE_RUN
   --reference-dir PROJECT/Data/Annotation/REVISION --panels PANELS.json
   --output {result_dir}/annotation --task-dir {task_dir}`. `PANELS.json` supplies
   `cell_type_order`, a parallel `palette` list, and `dotplot_markers` keyed by
   exactly those proposed labels. Derive these from this run's marker review.
   The tool verifies source-task evidence, reference provenance, exact cell IDs
   and cluster membership. It writes a new H5AD, marker dotplot/source tables,
   confidence/evidence, and composition tables; approval remains false.
2. Use `render_embedding_revision.py` on that declared H5AD, depending on the
   first task. Include candidate cell type, confidence, Leiden, sample, condition
   and QC panels. Its source declaration names the new producer task and digest.
   Inspect the final PNGs, record visual review, and link the complete revision at
   the top of the results index. Preserve the original numerical artifacts.

There is no requirement to rerun a baseline or obtain approval before producing
these candidate figures. The helper applies evidence-based proposals; it does
not autonomously infer labels inside a batch job. The active agent owns that
step. If a user requested only job startup, explicitly state any remaining
annotation work; a batch completion hook is not an unattended annotator.

`Notebooks/scanpy_workflow.ipynb` is the implementation, not a copy of one: the DAG's scanpy task runs `run_scanpy_notebook.py`, which writes a parameter sidecar and executes that same notebook through a kernel, so there is one code path rather than a notebook and a batch script that must be kept in step. `Scripts/Scanpy/README.md` documents the full ten-step notebook flow, the verification loop, and the completion standard; `Scripts/Scanpy/Report.md` is the bilingual evidence ledger. `Notebooks/example_ipf_scanpy.ipynb` is a shipped worked example that the DAG never executes — including its reviewed cluster-to-cell-type mapping, which is valid only for that example's exact cluster set and must not be transplanted.

## Figure standard

All intermediate, candidate, baseline and publication UMAPs use the shared `Scripts/Common/embedding_plot.py` helper. `save_embedding(figure, path)` exports an **8 × 8 in square canvas**, including its legend, at **300 dpi (2400 × 2400 px PNG)**. Do not generate PDF/SVG or duplicate preview/review images. Never use `bbox_inches='tight'` for these exports: a tight crop changes the canvas shape. The helper overrides even a global `savefig.bbox='tight'` setting.

Single-panel axes remain 4 × 4 in; comparison figures fit smaller square panels into the same canvas (two panels are stacked at 3.04 × 3.04 in each; larger comparisons use a grid). Construction and export both use the shared `panel_positions()` rule; the notebook's `figure-standard` cell imports helpers, rather than defining another geometry. `square_panels()` first gives before/after views a common data window; the shared exporter preserves that window and equal aspect without stretching coordinates. Compare like-for-like single panels across rounds rather than a single plot to a smaller overview panel.

Categorical legends use **one vertical column on the right**, preserving colours and category order; long display labels wrap and crowded legends reduce font size. Continuous colour bars use **one vertical bar per numerical panel**, outside its square axes. If a comparison cannot fit readable keys, export its panels separately; do not silently add a second legend column or clip labels. Numeric Leiden labels placed on the data are unchanged. Dotplots, heatmaps and non-embedding QC charts retain content-appropriate layouts.

The same exporter is required in manually authored final/publication rendering helpers. Do not change scientific coordinates, clustering, labels or palettes just to achieve this layout. The shared Python source is part of `code_signature`; adopting it in an existing generated project requires a fresh plan and validation, not overwriting an in-flight run. Updating this skill does not retroactively redraw existing outputs.

## Batch comparison

The comparison task reads the completion summary annotation_key and its declared h5ad. Candidate labels remain candidate_cell_type; reviewed labels use cell_type. The sample field is cohort and the coordinate basis is X_umap_after_harmony. See [batch delivery](figures-comparison.md) for the atlas canvas exception, source colours and visual review.
