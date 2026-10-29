# Hierarchical RNA annotation and presentation

Use when the user requests broad classes, subtypes and within-subtype analysis.
Keep one canonical delivery entry containing global figures and links to each
parent's analysis. A Level 3 collection does not replace the global Level 1/2
view. Do not hard-code a particular study's classes, sample counts or thresholds.

## Preserve the hierarchy

- Level 1: broad lineage or explicitly unresolved-state grouping.
- Level 2: evidence-supported subtypes; preserve the original labels in their
  own column when aggregating Level 1.
- Level 3: biological candidate subtype/state annotations within selected
  Level 2 parents. Keep local Leiden IDs separately; cluster numbers alone
  are not completed biological annotation.

Record parent selection thresholds, cell counts and sample support. Keep
ineligible cells explicitly marked as not subclustered. Stress/cycling/mixed
expression can describe state rather than lineage; do not silently merge these
into a supported cell lineage or claim every annotated group is a new cell type.

For independent parent analyses, reuse the agreed upstream singlet/QC subset.
Start from the verified full-gene normalized expression or raw counts with an
explicit normalization choice; do not re-select HVGs from the parent's inherited
HVG-only matrix. Independently run HVG/PCA, appropriate batch correction,
neighbors, clustering and UMAP. Preserve the global embedding separately;
local UMAP coordinates across parents are not a common embedding.

Use this run's full-gene markers, expression fractions, sample support and any
requested reference correlations to propose labels. Apply the normal Scanpy
automatic review/iteration policy within each parent; record accepted/rejected
candidates and stopping reasons. Deliver the first complete candidate annotation
without waiting for biological approval; mark it FOR REVIEW. Do not repeat QC
or doublet removal unless the user requests a changed filtering analysis.

## Ordered global figures and classification explanation

When continuing an existing project, inspect its selected archived figures,
legend settings and classification mapping. Reuse the established biological
order and palette unless a change is requested. Never derive display order from
first cell occurrence, alphabetical sorting or cluster size by default.

Export an ordered broad-to-subtype mapping with counts and a short explanation
of each broad group and unresolved states. Show group headings in the subtype
legend, keep each label on one line, and use the same order/colours in UMAP,
composition, dotplot rows and marker triplets. The broad-class UMAP must name
its classes. Include both global Level 1 and Level 2 views in the canonical
entry even when the latest work concerns Level 3.

Each selected parent receives normal annotated UMAPs, a full integrated overview,
composition, three supported genes per annotation in the dotplot, applicable
numbered reference heatmaps, comparison and an executed report. Include an
annotated collection figure and explicit links from the canonical entry.
Follow [the RNA overview contract](rna-overview.md): PNG only, compact A–O layout,
doublets in UMAP row three. When the user explicitly allows missing diagnostics,
keep labelled placeholders in the agreed positions and record the inherited
QC/doublet sources. This is a scoped exception; do not invent values, recompute
unrequested filtering, or report a failing standard full-delivery gate as passed.

## Self-check before delivery

Check global Level 1/2 figures and explanations, all selected parents, ordered
legends, per-annotation marker triplets, individual figures, integrated and
collection figures, source tables, reports and hash-bound visual reviews.
Preserve cell identities, global coordinates and upstream labels during styling.
Inspect final PNGs for clipped labels and overlapping legends; a numerical
manifest check cannot determine visual legibility or biological correctness.

For a standard global subtype overview, declare `annotation_hierarchy` in its
manifest and run `audit_rna_overview.py --require-classification` in addition to
the applicable full-delivery checks. See its schema in [RNA overview](rna-overview.md).
For a scoped custom bundle, export the equivalent mapping/count/source checks
and named deliverables, and report any standard-gate incompatibility explicitly.
Do not rewrite frozen manifests just to make an older analysis adopt a new schema.
