# Shared RNA–DNAm markers: selection, counts and presentation

Use for paired marker plots, shared/unique-marker inventories and revisions of
an existing marker figure. This is identity-marker analysis; use
[disease analysis](methylome-disease.md) for condition effects.

## Freeze the statistical definition before selecting display genes

Record the full gene universe and stable gene IDs, target-versus-rest labels,
RNA layer, DNAm region/normalization, eligible cells, tests, adjustment families,
effect directions and support thresholds. Join modalities on stable gene ID plus
cell type; retain differing source symbols and annotation versions. Resolve gene-ID
version stripping explicitly and detect collisions rather than silently collapsing them.

For a literature-based recipe inspect the actual Methods/code and cite the
specific implementation. Do not deduce normalization from a negative colour bar.
Separate an exact reproduction from a study-specific adaptation. In particular,
`M >= k AND U >= k`, `M >= k OR U >= k`, and `M + U >= k` are different depth rules;
ambiguous prose must not silently become a stricter conjunction. Retain the chosen
formula and any unresolved source ambiguity. Published thresholds are not universal
lung/tissue QC requirements.

Cell-level one-versus-rest tests can supply descriptive identity markers. Their
P values do not establish subject-replicated disease effects. Dual-modality
intersection does not eliminate subject/batch confounding or pseudoreplication.
Keep per-subject coverage and direction support as separate evidence unless an
additional eligibility rule was explicitly prespecified.

## Report every filtering stage in two units

A gene–type combination is one gene supported for one type. A gene present in
several types contributes several combinations but only one distinct gene.
Export a row-level audit and counts overall and by type, including:

1. Input gene universe and target/rest support eligibility in each modality.
2. RNA positive-marker criteria and DNAm hypomethylation-marker criteria.
3. Same-gene, same-type intersection.
4. Each explicitly defined uniqueness variant.
5. Display nominations and the independent genes actually plotted.

Use a stable pair key. Expose every pass/fail flag and effect/statistic; distinguish
sequential losses from independent exclusion reasons, which can overlap. Do not
sum overlapping failures as if they were a partition. The adjusted-P denominator
is the stated tested family, not the eventual shared or displayed subset.

## Uniqueness depends on where it is applied

Let R and D be all eligible marker pairs in RNA and DNAm; shared pairs S=R∩D.

- **Shared candidate:** pair belongs to S, with no uniqueness requirement.
- **Unique within the intersection:** its gene occurs in exactly one type in S.
- **Unique in each modality:** the gene occurs in exactly one type in R and in
  exactly one type in D, and those two types agree.

These sets need not match. A gene shared uniquely in S can remain a marker for
other types in R or D. Name the exact definition and preserve old results when
changing the presentation; do not relabel a relaxed definition as the original test.

## Layer the presentation without silently changing discovery

A useful delivery separates the complete shared candidate table, a representative
main figure and a strict uniqueness supplement. The main figure need not require
uniqueness. Freeze a ranking rule based on declared support/effects before rendering;
label a display cap as a cap, not a statistical threshold. If a type has few or no
eligible genes, show that shortage rather than adding unqualified canonical markers.

When a gene is nominated by multiple types, show one row and list all supporting
types, or deliberately repeat it with that policy stated. A grouping bracket or
dashed line based on first nomination does not imply type exclusivity. Export
both nomination combinations and plotted distinct genes, including passing genes
omitted from the display. Subject consistency used for ranking is not automatically
a new hard filter or a subject-level significance test.

## Make dotplot colour and support interpretable

Bind each plotted value to its source layer and formula. Label examples correctly:
raw gene-body M/C; mean of normalized single-cell DNAm values; mean log1p-normalized
RNA; mean of single-cell Z-scores; or Z-score across type means. These operations
are not interchangeable. State scaling axis, weighting, degrees of freedom,
missing/zero-variance treatment and display limits; export unclipped values.

Gene-body methylation is not universally anticorrelated with expression. Inspect
signs in the data. Do not negate values merely to produce a prettier diagonal.
If sign inversion is used for a defined integration method, retain raw layers and
explain the purpose. Do not call normalized scores a methylation percentage or
RNA type-mean Z-scores `ScaleData()` output without that actual computation.

Declare what dot size represents; constant size needs no invented detection-rate
legend. Include finite/covered-cell counts and mask unsupported DNAm means.
Shared-marker dotplots do not automatically require four DMR heatmap views;
follow the applicable [figure contract](publication-figures.md).

For a presentation-only revision verify unchanged source hashes, tested pairs,
P values, thresholds and counts. Deliver selection rules, stage counts, complete
candidates, uniqueness definitions, nominations, plotting values/support, figure
manifest and a separate visual review.
