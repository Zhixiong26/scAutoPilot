# RNA overview delivery contract

Use for a full RNA handoff or an explicitly requested integrated overview. A
narrow appearance edit does not expand into a full analysis. User-specified
layouts or marker counts override the defaults; record the chosen contract.

External expression-reference annotations follow the
[cluster correlation protocol](rna-reference-correlation.md), including numbered
correlation heatmaps and one owning delivery root for related figures and tables.

## Main PNG and supporting figures

Every full automated Scanpy delivery includes one readable integrated PNG.
Default layout places doublet diagnostics in the THIRD UMAP row, after annotation
and QC; the accepted default is fixed. A later explicit layout change requires
a recorded scoped override rather than silently changing this contract. Use these panels on the same canvas:

| Panel | Content |
|---|---|
| A–E | Cell annotation, Leiden, sample, verified condition, annotation confidence |
| F–H | Total RNA counts, detected genes, mitochondrial count percentage |
| I–L | Before-filter clusters, singlet clusters, pre-filter doublet class and score |
| M–N | Composition within condition and within sample |
| O | Marker dotplot in the same annotation order as A, M and N |

Derive all counts and titles from the current source. Preserve saved coordinates,
cells and palettes; do not recompute PCA or UMAP to repair presentation. Keep
square, equal-unit UMAP axes; use a large rectangular 300-dpi canvas for the
integrated figure. Avoid fixing the canvas to one study's dimensions or label
count. Export standard individual UMAPs at 2400×2400 pixels, 300 dpi.
Missing condition/confidence/QC metadata must be named with an explicit omission
in a scoped delivery; do not invent it or claim a complete full-RNA delivery.

Group similar subtypes by a recorded hierarchy, and keep every cell-type name
on one line in legends, row labels and composition panels. Allocate room before
reducing text size. Use consistent category order and colours across panels.
Render complete candidate labels with FOR REVIEW in the figure; biological
approval is separate from visual acceptance. All-placeholder annotations are
unfinished. Do not add separate preview/review images or PDF/SVG copies.

Doublet diagnostics are required whenever doublet filtering was performed,
including automated and custom Scanpy analyses. Integrate the four panels in
the main PNG; a standalone four-panel montage alone is insufficient. Retain
the standard individual source PNGs: before-filter
clusters, reprocessed singlet clusters, pre-filter doublet class, and pre-filter
doublet score. Class and score share the exact pre-filter coordinates/cell set.
Independently recomputed before/after cluster numbers are not matched identities.
If pre-filter coordinates are absent, compute them as an explicit signed task;
do not substitute an older, differently filtered run. Export calls/counts and
record capture IDs, parameters, input set and coordinate provenance. These
diagnostics join the overview, composition and dotplot in the final A–O canvas.
If doublet handling is explicitly not applicable, record a hash-bound decision
source and reason; a legitimate omission uses the eleven core panels, never
invented coordinates or an unexplained blank panel.

## Annotation level and markers

For broad classes, subtypes and independent within-subtype annotation, follow
[hierarchical RNA annotation](rna-hierarchy.md). Keep the global Level 1/2
figures and classification explanation in the canonical delivery alongside
Level 3 results; parent-specific collections do not replace them.

Record the plotted annotation column and level (major type, subtype or mixed
type/state labels). For RNA–DNAm work a major-type main view and RNA subtype
supplement may be appropriate; do not assume methylation resolves RNA subtypes.
Keep both columns and a versioned mapping. Merge labels only with user scope and
biological evidence; shared markers alone do not demonstrate a PCA defect.
Recompute composition and marker summaries after a merge. State groups such as
stress or cycling remain explicitly lineage-unresolved unless separate evidence
supports lineage. Do not delete them merely for being uncertain.

Default: **three distinct, evidence-supported genes per displayed annotation**.
Select from this run's evidence and suitable references, check each against the
full-gene expression source, and record the selection basis. Do not pad with
unsupported genes or pick genes merely to draw a diagonal. If three cannot be
supported, report the shortfall and continue interpretation; never silently
deliver two as a complete three-marker panel. Provisional states use state
markers and retain their uncertainty. Three genes do not establish identity.

Export `tables/marker_triplets.tsv`: `cell_type`, `marker_1`, `marker_2`,
`marker_3`, `marker_count`. Three-per-type does not imply global uniqueness or
specificity: shared genes may occur in multiple groups. Deduplicate matrix
columns, retain the group mapping, and report both unique genes and marker
assignments. If rendering repeated columns, give them explicit group labels.
The checker expects deduplicated matrix columns.

Export `marker_mean_log_expression.tsv` and `marker_fraction_expressing.tsv`,
rows in annotation order, columns in first-occurrence marker order. Use full-gene
log-normalized RNA by default, not batch-corrected values or an HVG-only matrix.
Specify colour scale and cutoff (`> 0` by default); area represents expressing
fraction. Preserve zeros and missingness. Missing genes must fail selection,
not become zero-filled columns. Gene-wise scaling is explicit and optional;
the standard mean table remains unscaled. Check all values are finite, fractions
in [0,1], and own-group markers have expression support.

## Evidence and acceptance

For a hierarchical global subtype view, also declare `annotation_hierarchy`:
`group_order` (ordered broad labels), `groups` (broad label to ordered subtype
list), `annotation_column`, `broad_column`, `mapping_table`, `guide`, and
`level1_figure`. Flattening `groups` in `group_order` must equal
`cell_type_order`. Export the mapping TSV with `cell_type`, `group`, `cells`
in this same order, and include both annotation columns in `panel_source.tsv`.
Register mapping, guide and global Level 1 PNG in `artifacts`; the guide names
and explains every broad group. Include the Level 1 PNG in the hash-bound visual
review. `audit_rna_overview.py --require-classification` rejects omitted
hierarchy metadata, reordered/missing categories, incorrect per-cell mappings
or counts, missing explanation/PNG and stale review. With the flag omitted,
declared hierarchy metadata is still validated; legacy non-hierarchical
manifests remain readable. This checks exported evidence, not label biology
or whether the rendered legend visually matches the declaration.

Export `sample_cell_counts.tsv`, `sample_cell_percent.tsv`,
`condition_cell_counts.tsv`, `condition_cell_percent.tsv`, and `panel_source.tsv`
(unique cell ID, sample, condition, cluster, annotation, confidence, QC and UMAP
coordinates). Percentage denominators are retained cells within each group.
Pooled-cell proportions are descriptive, not donor-level inference. Report
biological replicate counts separately from cell counts.

The overview adapter writes `delivery_manifest.json` with `source_sha256`
(resolved source paths to digests), `figure`, `pixels`, `dpi`, `panels` A–O,
`cells`, `candidate_types`, `cell_type_order`, `markers` (unique count),
`markers_per_annotation`, `marker_triplets`, `figure_format_policy: png_only`,
`dotplot` (colour and area definitions), `composition` (denominators), and
`artifacts` (`path`, `sha256`, `bytes`, relative to the manifest directory).
Also record annotation revision/level/status, coordinate basis, palette and
selection evidence in settings/source artifacts. Project-specific renderers
remain compute tasks; the skill does not yet provide a universal automatic RNA
renderer. The executor automatically audits new RNA summaries, and the run
inspector reports `awaiting_complete_delivery` until the complete delivery passes.
Rendering and marker interpretation remain required agent work, not a user
prerequisite. Do not label a numerical-only run as complete delivery. Never advertise successful comparison rendering as this overview.

Inspect the final main PNG and representative categorical/numerical single
panels. Record `visual_review.json` beside the manifest: `status: passed`,
`reviewer`, `notes`, `manifest_sha256`, and `inspected` mapping actual image
relative paths to SHA-256. Do not manufacture visual review from passing tests.

Run `tools/audit_rna_overview.py --manifest MANIFEST --require-full --output AUDIT.json` for a
scoped overview check. At full handoff, also run `audit_delivery.py` with
`--overview-manifest MANIFEST`, the scientific source runs, and other promised
files via `--require`. Project `config/figure_delivery.json` can make it
mandatory without repeating the argument:

```json
{"rna_overview_manifests": ["Results/runs/scanpy/RUN/delivery_manifest.json"]}
```

Update this pointer when a new overview replaces the main delivery. The checker
requires the overview producer to be included via `--source-run` at full handoff.
The candidate completion settings also default to three markers; an explicit
user override uses `markers_per_annotation` plus `marker_count_reason`.
The standalone overview checker accepts `--markers-per-annotation` for a scoped
override; the standard full-delivery profile enforces three.
The checker
verifies inventory/hashes, PNG sizes, panel coverage, marker mapping and tables,
composition arithmetic, and fresh review. It cannot prove biological specificity,
image readability or that a renderer actually used the declared values; inspect
those directly. Historical manifests remain historical; don't retrofit approval
or reseal outputs merely to pass a newer contract.

## Full-delivery manifest and automation

New integrated deliveries set `delivery_contract: rna_full_v2` and `panel_roles`
(letter to semantic role). The 15 roles are `cell_type`, `leiden`, `sample`,
`condition`, `confidence`, `total_counts`, `detected_genes`, `mitochondrial_percent`,
`doublet_before`, `doublet_after`, `doublet_class`, `doublet_score`,
`composition_condition`, `composition_sample`, `marker_dotplot`. Panel letters
follow the displayed order; changing row position does not change source data.

`doublet_diagnostics` records `status: performed`, `method`, `before_cells`,
`after_cells`, `before_table`, `after_table`, `class_column`, `score_column`,
`singlet_label`, `doublet_label`, `same_before_coordinates_for_class_and_score:
true`, and `cluster_numbers_are_independent: true`. Register both tables as
artifacts. Both contain unique `cell_id`, `leiden`, `UMAP1`, `UMAP2`; the before
table also contains calls and finite scores. The main `tables/panel_source.tsv`
contains the same fields for retained cells. The checker verifies that called
singlet IDs exactly equal after/main IDs, with matching after/main clusters and
coordinates. Record per-capture parameters and counts in source artifacts too.
For `status: not_applicable`, require `reason` and `decision_source`; the latter
must be in `source_sha256`, and the eleven core roles remain mandatory. This
exception is for an explicit scientific/scope decision, not missing work.

Keep the canvas compact by sharing column alignment, reducing unused whitespace
and allocating adequate legend space. Never stretch embeddings, clip labels,
reduce plot readability or change science to fit. Preserve a requested original
when the user asks to see a new proposal. Inspect final PNGs directly.

New built-in RNA plans and custom `scanpy` plans freeze the full-delivery
contract. After `workflow_summary` succeeds, `run_task.py` writes
`.workflow/runs/<id>/delivery_audit.json`; `inspect_run.py` reruns the gate before
setting workflow completion. Successful numerical tasks remain completed, so
missing figures/review do not require repeating analysis. Historical plans
without this contract remain historical. `audit_delivery.py --routes scanpy`
now requires registered full overviews even when config was omitted.

For an intentional multi-run delivery, `config/figure_delivery.json` may add
`run_bindings: {RUN_ID: {comparison_run: ID, source_runs: [IDs],
annotation_run: ID, required: [paths], overview_manifests: [paths]}}`. Bindings
are per run and source evidence is still validated; they do not promote an
unrelated old figure. Keep `rna_overview_manifests` current. A nested overview
may live beneath its declared producer root. No config switch disables the full
Scanpy gate; use the scoped overview checker for a narrow appearance proposal.

## Shared approved geometry

Use `tools/rna_overview_layout.py:create_canvas()` to obtain the figure, axes
keyed A–O and layout specification. Fill the axes with verified source data;
call `record_layout(figure, axes, specification)` after drawing and save the
returned record as manifest `layout`. Set `panel_roles` to the specification’s
exact mapping, and include the actual `samples` count. The checker compares
actual axes against `geometry()` for the recorded type/gene/sample counts and
longest label, including third-row doublets and square UMAP axes. It also reads
PNG pHYs resolution; a manifest claiming 300 DPI is insufficient.

Base dimensions are 32×27 inches (9600×8100 at 300 DPI). More rows, genes,
samples or long labels expand the canvas without changing its role order.
Use the same sample/type order in all tables. This helper is reusable geometry,
not a general annotation renderer; adapters still supply data, legends, colour
bars and visual review. Do not hardcode a cohort name or label count in the skill.
Full delivery now requires `rna_full_v2`; v1/A–K manifests remain readable with
the scoped historical checker and are not retroactively promoted.

```python
from rna_overview_layout import create_canvas, record_layout
fig, axes, spec = create_canvas(n_types, n_genes, n_samples,
                                 max(map(len, cell_type_order)))
# Populate A–H from retained-cell data; I–L from matching doublet evidence;
# M–N from composition tables; O from marker mean/fraction tables.
# Set equal-span x/y windows for each UMAP; add outside legends/colour bars.
manifest['panel_roles'] = spec['panel_roles']
manifest['layout'] = record_layout(fig, axes, spec)
fig.savefig(output_png, dpi=300, bbox_inches=None, facecolor='white')
```

The helper does not fabricate missing source data or issue a visual pass. Record
three separate decisions: rendered/artifact-verified, visually checked, and
biologically approved. User acceptance of this layout sets only the layout
policy; future candidate biological labels remain FOR REVIEW.
