# Within-type disease analysis and same-cell mechanism follow-up

Use after a frozen atlas/annotation handoff. Keep identity-marker results as a
baseline; condition testing is a new branch, not a relabeling of identity markers.
This protocol requires explicit statistical adapters and environment checks;
it does not imply that a packaged disease-DMR DAG or clinical metadata exist.

## 1. Subject-by-type analysability

Audit every requested defined type across all subjects before modelling. Export
subject, condition, type, cell count, RNA library/detected-gene information, DNAm
coverage/support, and subcluster composition. Include zero-count combinations.
Keep unresolved/Mixed cells descriptive unless their analysis role is resolved.

Prespecify minimum information per subject/type, per gene/region and per condition;
record the effective subject IDs, not only counts. Pooled depth in a type does not
ensure replication across subjects. A percentage threshold needs an explicit
denominator (all enrolled versus eligible subjects); do not automatically impose
70% in both groups or any previous project's numerical cutoffs.

Separate routine within-type comparisons, types driven by few subjects,
condition-depleted candidate states, and types sparse in both conditions.
Absence of measurements is not absence of a cell state. Sparse in both groups
must not be described as disease-specific. Missing controls may call for a state
or composition analysis, not a routine within-type differential test.

## 2. Subject-level gene and region models

Aggregate raw RNA counts by subject × type; aggregate DNAm methylated counts M
and total coverage C at the same unit. Do not pass Harmony-corrected embeddings,
scaled expression or normalized DNAm display values as raw counts. Retain
per-subject support and the composition of contributing cells/CpGs.

Use biological subjects as replicates. An applicable RNA model is edgeR robust
quasi-likelihood or DESeq2 pseudobulk with its own expression filter and documented
design. Use coverage-aware DNAm count models appropriate to the experiment.
A DSS-style gene-unit beta-binomial adaptation must be labelled an adaptation:
synthetic positions used to index genes are not genomic DMR coordinates.

Define condition contrast, covariates and multiple-testing families before looking
at discoveries. Adjust only available, estimable covariates; inspect design rank
and condition–batch confounding. A subject ID cannot be both a saturated fixed
effect and a separately estimable between-subject disease contrast. Do not claim
adjustment for age, sex, smoking or batch when metadata are absent.

Test the full eligible universe, then annotate previous markers. Do not restrict
new disease discovery to identity markers. Export effects with units, uncertainty,
raw/adjusted P values, tested family, group-specific subject support, coverage
eligibility, and why an item was not tested. Keep within-type and pooled-across-type
FDR separately named when both are reported.

For DNAm distinguish model-weighted effects, equal-subject mean ratios and
coverage-weighted pooled ratios; report sign disagreements. Unequal CpG coverage
can mimic a difference in aggregate gene-body ratios. Use common-CpG/coverage
sensitivity when the underlying counts support it; distinguish discovered sites
from all covered CpGs within a fixed region.

Leave-one-subject-out (LODO) output includes omitted subject, effect, direction,
model feasibility and the rule used to summarize stability. Say whether the model
was refitted or only an equal-subject descriptive effect was recomputed. Direction
consistency is not a new significance test, and ineligible folds do not silently
count as stable. Opposite RNA/DNAm directions prioritize hypotheses, not causality.

Backfill historical marker pairs by stable gene ID/type with disease effects,
statistical evidence, eligible subject counts, LODO, shared/unique/display flags.
Nonsignificant means insufficient evidence at the stated threshold, not stable
or unchanged. Equivalence needs a prespecified margin and an appropriate test.

## 3. Regions and same-cell association

Use subject-replicated CpG/region counts to locate disease changes before a
regulatory claim. Identity DMRs, VMRs and pooled-cell type differences do not
substitute for disease DMRs. Record coordinate/build conventions, blacklist
status, covered CpGs and regional FDR. A nominal or Top-N pilot is not confirmed
region-level FDR discovery.

A historical DMR can be reused after verifying the exact cohort, labels, group
eligibility, CpG filters and native producer evidence. Label it reused discovery
with new sensitivity analysis; do not imply it was newly called or globally
FDR-adjusted. Preserve historical entries while flagging unreliable regions out
of a new mechanism branch. Mapping/repeat concerns need suitable alignment or
mappability evidence; ALLC counts alone cannot resolve them.

Require physical same-cell evidence and a unique sample-plus-barcode map before
calling an association same-cell. Subject-paired or transferred labels support
other analyses but not that claim. Start with coverage-eligible pairs within a
type; record cell support, RNA detection, distinct values and effective subjects.

A pooled-cell correlation can be driven entirely by condition/subject means.
Use within-subject relationships, a justified hierarchical model or an explicitly
labelled subject-level meta-analysis. Check coverage, RNA library/detection,
condition and cell state as permitted by the design. Report the transformation
and uncertainty method; a residualized rank/Fisher-Z adaptation is not a direct
Spearman test on all cells, and its small-subject approximation needs caveats.
Condition-specific coupling requires adequate subjects in each group. Missing
support yields not-testable, not zero correlation or a nonsignificant tested result.

Gene-body associations can precede regional mapping, but cannot locate a promoter
or enhancer mechanism. Distinguish overlap, promoter links, nearest genes and
experimentally supported regulatory targets. Export the relationship used for each
region–gene pair; proximity alone is not a validated enhancer target. Cross-sectional
pseudotime may describe ordering; it does not establish temporal or causal direction.

## 4. Motifs, programs and candidate mechanisms

Separate low- and high-methylated disease regions for motif questions. Prespecify
an eligible tested-region background and matching on factors such as length, GC,
CpG density, coverage and chromosome context. Record exclusions and matching
success. If targets/background are insufficient, report that limitation rather
than relaxing calipers until enrichment appears.

A motif sequence scan is not motif enrichment, TF binding, TF activity or causal
regulation. Keep those evidence types distinct. Resolve TF aliases/families and
uncertainty explicitly. Combine valid region evidence with subject-level TF
expression and a named target-program method. A custom signed-mean score is not
an execution of decoupleR or another named method. For functional enrichment use
the tested/mappable gene universe and track many-to-many region–gene mappings.

Prioritize candidate chains with regional effects, a justified gene link,
subject-aware expression/coupling, TF/program evidence, coverage/mappability
quality and LODO support. List missing links. DNMT/TET RNA abundance is not an
enzyme activity assay. Neither opposing effects, motif presence nor pseudotime
alone establishes a regulatory mechanism.

## Delivery evidence

Keep analysability, all eligible tests, historical-marker backfill, LODO,
region reliability, pair eligibility, motif/background audit and candidate-chain
status separate. Use machine-readable states such as tested, not_testable,
insufficient_evidence, reused_discovery and execution_failed. A completed workflow
can legitimately yield no supported mechanism; report what was tested and what
could not be tested. Follow native output/index contracts and figure review.
