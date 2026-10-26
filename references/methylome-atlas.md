# Methylome atlas and RNA integration

Use this protocol for a multi-subject methylome atlas or paired RNA–DNAm study.
For software timing/equivalence use [benchmarking](methylome-benchmark.md);
for marker presentation use [shared markers](methylome-markers.md);
for within-type disease inference use [disease analysis](methylome-disease.md).
These are agent-managed protocols using existing custom DAG contracts, not a
new automatically implemented atlas route. Check adapter readiness before submission.

## Establish the experiment and preserve its baseline

Resolve the actual subject count, conditions, independent capture libraries,
cell inclusion authority and annotation revision from manifests. A manuscript
example or pasted design is not evidence for the project's cohort size.
Distinguish subject pairing, matching barcode strings and physical same-cell
measurement. Record user/experimental confirmation separately from the validated
sample-plus-barcode map; confirm a one-to-one join and report unmatched cells.
Do not invent an assay protocol or missing clinical metadata.

Record available modalities before choosing branches. DNA methylation plus RNA
does not provide chromatin contacts: no compartments, TADs or loops can be inferred
as measured 3D data. GWAS/clinical extensions require their own inputs, ancestry,
genome build and analysis design; they are not prerequisites for an atlas.

Freeze source cells, references, labels, layer definitions, cohort exclusions
and input/producer signatures. Continue an explicitly selected historical cohort
without retrospectively claiming it passed newer doublet policy. For a newly
requested paired QC analysis read [paired doublets](paired-doublets.md).
Separate scientific reruns, annotation revisions and presentation-only revisions.

## Feature roles are distinct

| Representation | Construction | Appropriate role |
|---|---|---|
| Fixed genomic bins | Declared width, genome build, chromosomes and blacklist handling | Initial cell representation; compare widths as separate feature experiments |
| VMRs | Method-specific variability discovery on a frozen cell universe | Alternative cell representation, with discovery parameters and retained regions recorded |
| Gene bodies/promoters | Declared gene annotation, transcript/TSS policy and boundaries | Marker evidence, modality comparison and region-level follow-up |
| Identity DMRs | Between cell types after annotation | Cell identity/regulatory interpretation |
| Disease DMRs | Between conditions within type, with subject replication | Disease association and mechanistic hypotheses |

A fixed-bin width is not the number of selected features. VMRs are not fixed bins;
identity DMRs are not disease DMRs. DMR-based reclustering is a separate,
label-dependent experiment, not an independent validation of those labels.

Preserve integer methylated counts M and total coverage C with 0 <= M <= C.
C=0 is missing methylation, not an unmethylated observation. Raw M/C, posterior
estimates, cell-global normalization, residuals and Z-scores are different layers.
MethylVI consumes integer M/C counts, not a hypomethylation or display score.
MethSCAn/vmrseq can internally use binary states and discard intermediate
methylation: document this transformation and retain the original counts.

For bin/VMR alternatives, freeze cells, chromosomes and comparison criteria;
record differing feature counts and coverage. Batch variables come from metadata.
Do not optimize away condition-specific states or use RNA-supervised separation
as independent evidence of methylome integration quality. Read
[methylation iteration](methylation-optimization.md) for ordinary versus weighted
views, seed stability and model/graph/layout boundaries.

## Annotation and completeness

Build methylome clusters and gene-body marker evidence, then compare against RNA.
If labels were transferred from RNA, call them transferred labels. Reusing them
for methylome marker tests is useful support but not independent annotation.
Numeric cluster IDs cannot be transferred across models without a verified map.

Audit all requested defined types. Keep unresolved/Mixed cells in an explicitly
descriptive category until resolved; never merge them into a convenient type to
complete a diagonal. Export cell-level labels, confidence, alternatives and the
cross-modal confusion table with counts and denominators. Disagreement may reflect
sparsity, doublets, state differences or annotation error; it alone does not prove
an epigenetically poised or transitional state.

Do not focus a full-atlas delivery on one tractable type without listing the
others and explaining their status. A useful completeness table has one row per
type and columns for subjects, cells, coverage, annotation evidence, marker
eligibility, identity-DMR eligibility, disease eligibility and missing inputs.

## Count caches and handoffs

Verify cached zero/invalid rows against raw ALLC interval counts before changing
priors or removing cells. Use independently queried genes/regions plus normal-row
controls. A completed flag is not proof that count data were flushed correctly.
Repair verified bad rows in a new artifact, retain source counts and document
whether the failure mechanism is known. Do not assign arbitrary priors to make
invalid rows pass or convert missingness into zeros.

Carry cell/feature IDs, coordinate convention, reference hash, source-file identity,
count layer semantics and producer evidence into every handoff. Region conversion
must use declared strand/CG semantics: canonicalizing a reverse-strand CpG can
require a coordinate shift and dyad aggregation. A reference-CpG intersection
can change the native site's universe; test it before claiming an equivalent shortcut.

Recommended deliverables are a cohort/QC ledger, sample-by-type information table,
annotated ordinary embeddings with source evidence, feature/normalization settings,
marker selection audit, and separate identity/disease result indexes. Use the
existing native task/index and [publication](publication-figures.md) contracts.
Unavailable branches get explicit reasons rather than fabricated empty results.
