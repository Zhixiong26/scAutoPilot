# Paired RNA–DNAm doublet policy

For paired RNA and DNA methylation, use one established detector per modality:
**per independent capture library: compare Scrublet versus scDblFinder once,
select one RNA detector → MethylScrublet → reconcile → one cell-level exclusion
list applied to both modalities**. scDblFinder is the proposed RNA choice, not
a predetermined winner. The authorized two-tool comparison is for selection,
not permanent stacking, union/intersection filtering or majority voting.
Do not add further RNA detectors or invent a new detection method. This is a workflow policy,
not a claim that the two calls are statistically independent or infallible.

## Identity and inputs

- Resolve `cell_id`, `library_id`, `donor_id` before fitting. A capture library
  is the physical unit in which doublets can form, not automatically a donor,
  sample directory, sequencing lane, or 96-well plate. Merge technical splits
  of the same capture; keep independent captures separate. A multiplexed capture
  can contain several donors. If capture identity is unknown, stop for metadata
  clarification rather than silently substituting sample IDs.
- Use the full eligible library after basic modality QC, before doublet removal,
  not a selected cell type, a 600-cell teaching subset, or only UMAP residuals.
  Keep all eligible cells available to each detector. Do not remove RNA-called
  doublets before fitting DNAm; otherwise the comparison is censored.
- RNA: original full-gene integer counts, not log-expression/HVG-only counts.
  DNAm: aligned original integer regional `mc` and `cov`, same cell/feature order,
  `0 <= mc <= cov`; no smoothed/imputed matrix or MethylVI/UMAP coordinates.
  Basic QC/coverage failures are separate from doublet calls.

## Official implementations and readiness

Compare [official Scrublet](https://github.com/swolock/scrublet) with
[Bioconductor scDblFinder](https://bioconductor.org/packages/release/bioc/vignettes/scDblFinder/inst/doc/scDblFinder.html)
for RNA under the selection procedure below. Record version, random seed, per-library cell counts, expected-rate
assumptions, thresholds, scores and calls. Expected rate is a prior, not a quota;
do not force a fixed proportion to be removed or use one universal loading-rate
formula for every chemistry. RNA singlet calls do not prove absence of doublets.

Use [ALLCools MethylScrublet](https://lhqing.github.io/ALLCools/cell_level/doublets/doublet_score_chrom100k.html),
imported from `ALLCools.clustering.doublets`, for DNAm. The documented interface
is `fit(mc, cov, clusters=...)`; verify the installed version and accepted data
types in an isolated compute smoke test. The official brain example uses CHN
and 100-kb features: do not transplant its context, bin size or thresholds to
lung mCG. Record region definition, coverage support, context and parameters.
If preliminary clusters are needed, use documented methylation-only preliminary
clustering, not RNA labels or supervised UMAP. This is a preparation step, not a
second detector. Pin a compatible official implementation; missing dependencies
or insufficient information become `not_run`/`insufficient`, never `singlet`.

Both modalities score the same physical cells where available; match by exact
validated cell ID, never row order or barcode alone across libraries. Scores
have different scales: do not average them or apply one shared score threshold.

## Reconciliation

| RNA call | DNAm call | Cell-level action |
|---|---|---|
| doublet | doublet | Prioritize removal under the declared filtering policy; preserve both original calls. |
| doublet | singlet | Review RNA score and marker evidence; remove when RNA evidence is reliable. DNAm negative does not veto removal. |
| singlet | doublet | Review methylation score, coverage, library/batch effects and RNA markers before deciding. |
| singlet | singlet | Retain for subsequent routine QC; neither call guarantees quality. |
| insufficient/not_run | detectable modality | Record missing evidence and decide from available evidence; absence is not a negative call. |

Concentrate cell-by-cell review on discordant calls and missing-evidence cases;
do not require exhaustive individual review of concordant singlets. Still check
per-library score/threshold behavior and anomalous detection rates for all runs.
High reads, bridge positions in UMAP and differing RNA/DNAm annotations are
**not standalone removal criteria**. A marker panel alone is not doublet truth.
After selecting the RNA method, do not bring the rejected tool or further RNA
voters back solely to settle an individual disagreement.

## RNA method selection: Scrublet versus scDblFinder

1. Freeze the same per-library, basic-QC-passing original full-gene counts and
   exact cell set before either tool filters cells. Existing Scrublet results
   are reusable only if these identities and the actual parameters are verified;
   results on an already filtered cohort are not a like-for-like comparator.
2. Run both official methods with recorded versions/seeds and library-specific
   expected-rate assumptions. Keep native preprocessing and score thresholds
   visible; compare calls, not raw score magnitudes. Test a small predeclared
   seed set on the same inputs to check call stability; do not tune toward a
   desired removal count or the cleanest UMAP.
3. Export `rna_method_comparison.tsv` containing IDs and both methods' scores
   and calls, a per-library 2x2 call table, concordance and retention summaries,
   and a discordant-cell worksheet. Review conflicting calls using raw RNA
   marker coexpression, library/QC context and score distributions. DNAm
   evidence is supportive, not an independent truth set or a target to maximize.
4. Prefer reliable independent doublet truth (hashing/genotype evidence with
   its detectability limits) if available. Otherwise select provisionally from
   stable, biologically supported calls and sensible per-library behavior;
   lower removal rate, higher tool agreement and prettier UMAP are not proof
   of superiority. Report missed homotypic doublets/uncertainty, especially
   where no ground truth exists. If no clear winner, record `selection_pending`
   and stop before new filtering; do not silently vote or change tools per cell.
5. Record the selected method and rationale in `rna_method_selection.json`.
   Use one selected RNA detector for the comparison scope; any library-specific
   exception needs explicit evidence and review, not cherry-picking. Populate
   `rna_score`/`rna_call` in the final nine-column table only from the selected
   detector. Keep both-tool results in the separate comparison file.

## Minimal final table and unified filtering

The final table contains exactly these columns; detailed evidence belongs in
separate run artifacts:

```text
cell_id  library_id  donor_id  rna_score  rna_call  met_score  met_call  final_call  removal_reason
```

`rna_call`/`met_call`: `singlet`, `doublet`, `insufficient`, or `not_run`.
Unavailable scores are NA, not zero. `final_call`: `keep`, `remove`, or
`review_required`; unresolved rows must not silently become keep/remove.
`removal_reason` is required for remove, empty for keep, and records the unresolved
or missing-evidence reason for review_required. A retained cell with missing
modality evidence keeps that limitation in its modality call and evidence record.

Preserve method versions, inputs/IDs/hashes, per-library QC and parameters,
score distributions, original calls and review decisions outside this compact
table. Resolve or explicitly quarantine review_required rows before delivering
a final paired cohort; quarantine is not confirmed doublet removal.

Apply the same finalized removal IDs to RNA and DNAm, preserving raw inputs.
For paired downstream analyses, verify the retained ID sets are identical;
report modality-specific QC failures and missing pairs separately, not as
doublets. Fit both detectors before applying this shared mask. Write a new run,
before/after counts by library and donor, and the table/hash used by all branches.
Changing retained cells invalidates downstream graphs, models and DMR inputs;
do not reuse cell-dependent results as if they were unchanged.

## Migration boundary (0.15.1)

This release updates agent instructions, not the packaged detector executor.
The shipped Scanpy notebook still contains legacy optional Scrublet and its
early RNA filtering. It does **not** implement the paired policy. Do not run
that legacy cell-removal path as the new workflow or merely rename its scores.
Before a new paired production run, deploy the RNA comparison and the selected
RNA/DNAm official methods with smoke
tests through an explicit signed DAG, disable legacy automatic Scrublet removal,
and verify both branches consume the reviewed shared mask. If that integration
is absent, report the gap and stop before destructive filtering; no silent
fallback. Pure RNA/DNAm projects use the available detector and explicitly mark
the other modality unavailable. Historical results and active frozen runtimes
remain unchanged; policy adoption does not retroactively delete cells.
