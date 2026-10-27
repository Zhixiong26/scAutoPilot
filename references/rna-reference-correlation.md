# RNA reference annotation by cluster correlation

## Scope and default

When annotating existing RNA clusters from an external expression reference,
use query-cluster to reference-cell-type Spearman correlation by default.
This is the RNA adaptation of group-profile matching; it is not methylation
VMR/DMR correlation. An explicit user-selected method takes precedence.
An exact, verified same-cell annotation table may still be joined by cell ID;
check uniqueness, coverage and provenance before interpreting IDs as shared.
Do not silently substitute per-cell PCA/kNN, majority voting or label transfer.
Do not run kNN as a prerequisite. Use the current validated RNA object directly.
Without a suitable expression reference, continue marker-based annotation under
[Scanpy annotation](scanpy.md); do not fabricate a reference.

This is an agent-executed protocol, not a new built-in CLI or automatic runtime
route. Implement and validate a parameterized project adapter, then schedule it
as a custom signed DAG. Never copy study-specific run IDs, paths, sample names,
cluster counts, thresholds, gene sets or label mappings into the portable skill.

## Inputs and expression contract

1. Freeze query H5AD identity, exact cell IDs, cluster membership, reference
   identity, reference label fields, species, gene namespace and expression
   layers/scales. Reuse saved clusters and embeddings. Annotation alone must
   not change cells, counts, raw/layers, PCA/Harmony/UMAP or neighbor graphs.
2. Align unique genes explicitly. Record duplicate/alias handling and the ordered
   shared gene list. Use a declared reference-derived variable-gene set shared
   with query, with its selection provenance, or a predeclared supported gene
   panel. Do not tune the gene universe to force preferred labels. Exclude
   missing/nonfinite profiles; zero-variance profiles have undefined correlation
   and require marker-based review, not a fabricated best match.
3. Use comparable uncorrected expression: when counts are available, normalize
   each cell by total counts to 10,000, then log1p. For existing normalized data,
   verify its documented scale instead of normalizing twice. Do not use scaled
   residuals, integrated values, PCA coordinates or methylation ratios as RNA
   expression. Record handling when input scales cannot be reconciled.
4. Calculate the arithmetic mean of cell-level log1p(CP10K) expression for each
   query cluster and each reference type. Mean(log1p expression) is not
   log1p(mean counts). Include zero-expression cells. Record cell support and
   sample composition; specify whether reference means are cell-weighted or
   donor-balanced. The default is cell-weighted. If reference sampling is needed,
   freeze the stratification, seed, selected IDs and weights before matching.
   Separate reference training and held-out donors/samples before fitting feature
   selection when reporting independent validation; disclose any feature leakage.

## Matching and review

Compute Spearman rho across the same ordered genes for every query-cluster /
reference-type pair (average ranks for ties). Save the complete matrix, query
and reference mean profiles and support counts. Assign each cluster its
highest-rho candidate and retain runner-up, top rho and top-minus-second margin.
Record exact ties and a deterministic display order; ties are ambiguous evidence.
Transfer this mapping to query cells by their own cluster membership.

If the reference supplies multiple label systems, run each independently using
its own centroids; keep separate result columns, heatmaps, marker evidence and
review status. Do not force every reference type to appear in the query or merge
label systems into one claimed consensus. Keep unused reference types in the
full heatmap. Absence of a winning cluster does not prove biological absence.

Review each proposed call against query markers, lineage consistency, QC and
sample composition. Preserve alternative labels and explicitly flag conflicts,
low rho, small margins, rare types and mixed/state-dominated clusters. Stress,
cycling and low-RNA states are not established lineages. Deliver a complete
best-supported candidate FOR REVIEW, with confidence and evidence; do not use
Unassigned as a completed proposal or silently grant biological approval.
Any marker-informed override must preserve the original correlation winner and
state the reason. Low support alone does not authorize deleting cells.

Optional gene-column bootstrap assesses sensitivity to feature resampling:
record seed, replicate count and winner agreement. It is not methylation block
bootstrap, a calibrated cell probability or independent biological replication.
Record confidence thresholds explicitly and justify them for the current data;
do not reuse a previous study's cutoffs as universally validated defaults.
Reference validation must name the unit (e.g. held-out sample-by-known-type mean
profile) and minimum support. Reference accuracy is not query accuracy, and
profile accuracy is not comparable to per-cell kNN accuracy without qualification.

## One delivery per annotation revision

Use one owning `Results/runs/scanpy/<run-id>/` for a newly planned annotation
revision, with tasks sharing its frozen `{result_dir}`. Put label systems in
named subdirectories and organize annotation, tables, figures, comparison and
reports within that root. Do not create sibling top-level runs merely for an
additional heatmap, overview, dotplot, comparison or label field. Independent
numerical producers may remain separate with explicit source links. A required
later signed render run may retain its own evidence/output root; register it as
a supplement through the existing canonical delivery entry, not a second final
annotation. Do not change a frozen result_dir to force consolidation.

Required delivery for each requested label system:

- Derived full H5AD or a verified annotation table bound to source cell IDs and
  clusters, with old labels retained; distinguish metadata-only plotting objects.
- Full correlation matrix and ordered genes; query/reference means and support;
  cluster mapping, per-cell labels, alternatives, confidence and review flags.
- Correlation heatmap PNG with every finite cell annotated to two decimals,
  readable contrast, full row/column labels and a clearly explained best-match
  indicator. Undefined values show NA. Preserve the full-precision matrix TSV.
- Integrated full RNA overview including doublet diagnostics and the marker dotplot, exactly three supported
  genes per displayed annotation by default; preserve lineage order and single-line
  type names. Never invent markers to meet the count: resolve evidence gaps or
  report an incomplete delivery. See [RNA overview](rna-overview.md).
- Publication comparison, individual embeddings, source tables, method/settings,
  provenance hashes, manifest, direct visual review and delivery audit. Only one
  final PNG per figure; no PDF/SVG or duplicate preview/review images.

Before handoff, verify exact query IDs/membership and unchanged scientific arrays;
check matrix dimensions, coverage, mapping-to-cell consistency, independent label
systems and marker triplets. Visually inspect final heatmaps and overviews.
Register all requested overviews in `config/figure_delivery.json`, run
`audit_rna_overview.py` and `audit_delivery.py` with required correlation tables,
heatmaps, source producers and comparison evidence. These existing tools check
artifact/figure completeness; the adapter must also validate correlation math
and cell alignment. A successful script alone is not complete delivery.

When the user chooses only cluster correlation, present one canonical current
entry per requested label system and retire superseded kNN figures. Delete old
results only within user-authorized cleanup, after dependency and active-writer
checks. Record removed paths and identities, keep required upstream evidence,
refresh indexes and rerun delivery checks. Never relabel kNN predictions as
correlation or discard required provenance to make a directory look cleaner.
