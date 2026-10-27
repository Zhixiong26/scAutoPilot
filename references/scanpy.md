# Scanpy: analysis, annotation and complete delivery

## Start from the requested stage

Read the project configuration, sample/capture metadata, selected source run,
completion evidence and saved annotation before continuing. Preserve read-only
RNA inputs and exact cell IDs (`cell_id_prefix` is explicit). New scientific
work uses a signed DAG on a compute node; figure-only work reuses saved data.
Do not rerun PCA, Harmony, neighbors, UMAP or Leiden to repair a figure.

The bundled notebook is the numerical Scanpy implementation for 10x directories,
ZIPs containing one matrix and 10x H5. Its legacy detector is per-sample Scrublet;
it is not an implementation of scDblFinder or joint RNA–DNAm doublet analysis.
If the user selected scDblFinder, use a validated per-capture adapter and record
its actual parameters/calls; never silently run legacy Scrublet instead. The
capture unit is an independent capture reaction, not necessarily a donor/sample.
For paired RNA–DNAm work, read [paired doublets](paired-doublets.md); RNA-only
scope does not authorize methylation filtering. Preserve pre-filter counts,
IDs, calls, scores and coordinate provenance needed for the final diagnostics.

Counts remain in the declared counts layer; document its gene universe. The
full-gene log-normalized matrix remains in `raw` or another explicitly declared
source. Do not imply an HVG-only counts layer contains full-gene counts.
Runtime or input changes require validation and a new plan. Do not modify an
active/frozen executor or infer current completeness from a Slurm exit code.

## Complete the annotation without waiting for the user

The notebook is a numerical producer, not an unattended biological annotator.
A numerical checkpoint marked `candidate_annotation_incomplete` is unfinished
agent work. Continue from saved markers/QC and complete a proposed annotation;
do not deliver all-Unassigned plots or ask the user to supply the initial labels.

Choose the applicable evidence route:

1. For a verified annotation of the same cells, join exact unique cell IDs with
   coverage/provenance checks. Do not infer identity from similar barcode text.
2. For an external RNA expression reference, use
   [query-cluster to reference-type Spearman matching](rna-reference-correlation.md)
   by default. Retain full numbered heatmaps, alternatives, confidence and marker
   review. kNN is an explicitly selected alternative, not a prerequisite.
3. Otherwise interpret this run's ranked markers, canonical lineage evidence,
   QC and sample composition. Record the genes supporting each proposal and
   preserve uncertainty. Never transplant numeric cluster-to-type mappings.

Keep major types, subtypes and states separate. Stress/cycling labels describe
states until lineage is supported; shared marker expression is not proof that
PCA is defective. A major-type revision keeps subtype labels and a versioned
mapping, then recomputes composition and marker summaries for the chosen level.
Low-confidence proposals retain alternatives and review flags; they do not
justify deleting cells. Complete candidate figures say FOR REVIEW.

To package a marker-reviewed worksheet (`cluster`, `cell_type`, `confidence`,
`alternatives`, `evidence`), use:

```bash
python tools/prepare_scanpy_candidate_reference.py --project PROJECT \
  --run-id SOURCE_RUN --worksheet PROJECT/config/proposals.tsv \
  --output-dir Data/Annotation/REVISION
```

Then plan `complete_scanpy_candidate.py` with the source run, reference directory
and panel specification (ordered types, palette, three supported markers/type).
It verifies exact cells/clusters and exports a derived H5AD, annotation evidence,
marker/composition tables. Use `render_embedding_revision.py` for standard
single panels when needed. **These helpers alone are not the full handoff.**
Continue through the complete main figure, comparison, notebook and delivery
checks below in the same annotation revision. Never require a baseline rerun
just to deliver candidate figures.

Biological approval is separate from layout/visual approval. Bind an actual
annotation decision to the exact revision, source signature and cell membership
using `record_annotation_review.py`; approving a picture does not approve DMR
labels. See [downstream review flags](iteration-practice.md#annotation-revisions-and-downstream-handoff).

## Fixed full RNA figure

Use [the authoritative overview contract](rna-overview.md) and shared
`tools/rna_overview_layout.py`. The approved default is:

| Row | Panels | Content |
|---|---|---|
| 1 | A–D | Cell type, Leiden, sample, condition |
| 2 | E–H | Confidence, total counts, detected genes, mitochondrial percentage |
| 3 | I–L | Before doublet removal, after removal, doublet class, doublet score |
| 4 | M–N | Composition by condition and by sample |
| 5 | O | Marker dotplot: three supported genes per displayed annotation |

Keep the canvas compact, square equal-unit UMAP axes, consistent palettes and
lineage-grouped single-line labels. The default 32×27 inch, 300-dpi canvas gives
9600×8100 pixels; the shared helper expands for more types/genes/samples or long
labels while retaining the same row order. Do not invent study names, counts,
markers or sample identities. Only an explicit later user request changes this
layout; record any override as a separately scoped delivery until validated.

Export one final PNG per figure, including required individual panels; no PDF,
SVG, preview/review duplicate PNGs or thumbnail/contact-sheet substitutes.
`Scripts/Common/embedding_plot.py:save_embedding()` exports individual UMAPs at
8×8 inches, 300 dpi, 2400×2400, with outside single-column legends and vertical
numeric colour bars. Its default `wrap_legend=False` keeps labels single-line;
do not restore old wrapping behavior. Main canvases use the shared overview
layout, not the square single-panel exporter. Check text/legend collisions
visually and grow the available space rather than hiding/truncating labels.

## One delivery and an executable completion gate

Plan annotation, source tables, heatmaps, overview and comparison together under
`Results/runs/scanpy/<run-id>/`; use subdirectories for label systems and artifact
roles. Necessary independent producers remain explicit source dependencies.
A later rendering run is a supplement linked from one canonical annotation
entry. User-approved pure appearance edits can overwrite figures with updated
hashes/review; when the user requests a new proposal, preserve the original.

The main manifest declares `rna_full_v2`, exact panel roles, actual geometry,
source hashes, marker and composition tables, doublet calls/coordinates and
visual review. `audit_rna_overview.py --require-full` checks the fixed layout,
actual PNG DPI/dimensions, marker triplets and exact before/after/main cell IDs.
`audit_delivery.py --routes scanpy` also requires valid producer evidence,
formal publication comparison, executed notebook, summary and current index.
A three-panel comparison atlas is supplementary and cannot replace the main PNG.

New built-in and custom Scanpy plans freeze this contract. Summary execution
automatically audits delivery, and `inspect_run.py` leaves the workflow at
`awaiting_complete_delivery` until the gate passes. Completed numerical tasks
remain completed. Continue agent annotation/rendering/review rather than
repeating science or calling incomplete outputs complete. Per-run overview
bindings override project display pointers so an unrelated old figure cannot
become a compulsory dependency. See [delivery audit](delivery-audit.md).

The shared helper supplies layout, not biological interpretation or a universal
renderer for arbitrary input schemas. A project adapter must populate it from
verified saved data, export actual geometry and source tables, and inspect final
PNGs. Missing metadata/markers or unavailable pre-filter data remain explicit
unfinished work; do not fabricate panels to silence the gate.
