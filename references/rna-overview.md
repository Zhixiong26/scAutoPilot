# RNA overview delivery contract

Use for a full RNA handoff or an explicitly requested integrated overview. A
narrow appearance edit does not expand into a full analysis. User-specified
layouts or marker counts override the defaults; record the chosen contract.

## Main PNG and supporting figures

Deliver one readable integrated PNG, with these panels on the same canvas:

| Panel | Content |
|---|---|
| A–E | Cell annotation, Leiden, sample, verified condition, annotation confidence |
| F–H | Total RNA counts, detected genes, mitochondrial count percentage |
| I–J | Composition within condition and within sample |
| K | Marker expression dotplot in the same annotation order as A, I and J |

Derive all counts and titles from the current source. Preserve saved coordinates,
cells and palettes; do not recompute PCA or UMAP to repair presentation. Keep
square, equal-unit UMAP axes; use a large rectangular 300-dpi canvas for the
integrated figure. Avoid fixing the canvas to one study's dimensions or label
count. Export standard individual UMAPs at 2400×2400 pixels, 300 dpi.
Missing condition/confidence/QC metadata must be named with an explicit omission
in a scoped delivery; do not invent it or claim a complete A–K delivery.

Group similar subtypes by a recorded hierarchy, and keep every cell-type name
on one line in legends, row labels and composition panels. Allocate room before
reducing text size. Use consistent category order and colours across panels.
Render complete candidate labels with FOR REVIEW in the figure; biological
approval is separate from visual acceptance. All-placeholder annotations are
unfinished. Do not add separate preview/review images or PDF/SVG copies.

When doublet diagnostics are requested, also deliver four PNGs: before-filter
clusters, reprocessed singlet clusters, pre-filter doublet class, and pre-filter
doublet score. Class and score share the exact pre-filter coordinates/cell set.
Independently recomputed before/after cluster numbers are not matched identities.
If pre-filter coordinates are absent, compute them as an explicit signed task;
do not substitute an older, differently filtered run. Export calls/counts and
record capture IDs, parameters, input set and coordinate provenance. These
diagnostics supplement the A–K overview, not replace it.

## Annotation level and markers

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

Export `sample_cell_counts.tsv`, `sample_cell_percent.tsv`,
`condition_cell_counts.tsv`, `condition_cell_percent.tsv`, and `panel_source.tsv`
(unique cell ID, sample, condition, cluster, annotation, confidence, QC and UMAP
coordinates). Percentage denominators are retained cells within each group.
Pooled-cell proportions are descriptive, not donor-level inference. Report
biological replicate counts separately from cell counts.

The overview adapter writes `delivery_manifest.json` with `source_sha256`
(resolved source paths to digests), `figure`, `pixels`, `dpi`, `panels` A–K,
`cells`, `candidate_types`, `cell_type_order`, `markers` (unique count),
`markers_per_annotation`, `marker_triplets`, `figure_format_policy: png_only`,
`dotplot` (colour and area definitions), `composition` (denominators), and
`artifacts` (`path`, `sha256`, `bytes`, relative to the manifest directory).
Also record annotation revision/level/status, coordinate basis, palette and
selection evidence in settings/source artifacts. Project-specific renderers
remain signed compute tasks; the skill does not yet provide an automatic A–K
renderer. Never advertise successful comparison rendering as this overview.

Inspect the final main PNG and representative categorical/numerical single
panels. Record `visual_review.json` beside the manifest: `status: passed`,
`reviewer`, `notes`, `manifest_sha256`, and `inspected` mapping actual image
relative paths to SHA-256. Do not manufacture visual review from passing tests.

Run `tools/audit_rna_overview.py --manifest MANIFEST --output AUDIT.json` for a
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
