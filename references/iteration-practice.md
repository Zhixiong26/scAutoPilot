# Evidence-led iteration and result selection

Use this workflow when asked to continue improving an analysis, diagnose a poor
UMAP, revise annotations, or compare methylation models. It incorporates the
IPF_final analysis experience; its sample names, cluster numbers, thresholds,
selected runs and approval decisions are not defaults for another project.

When the task calls for established methods or stronger validation, route to
[literature-backed methods](published-methods.md). Select the relevant protocol
and disclose deployment/adaptation status; do not run every listed method or
claim a published name for the existing local heuristics.

## Decide what actually changes

| Request / diagnosis | Work to perform | Evidence to preserve |
|---|---|---|
| Layout, legend, palette, panel size | Render existing coordinates in a new figure revision | Cell IDs, coordinates, labels, graph and source hashes unchanged |
| Revise a biological label or level of detail | Re-examine this partition's markers, then export a separate annotation revision | Cluster membership and coordinates unchanged; old/new labels and rationale |
| UMAP fragmentation | Examine the high-dimensional graph, QC and sample composition before tuning layout | Connectivity, neighbor preservation, lineage markers and fixed-style figures |
| Change neighbors, PCs, resolution or min_dist | A new candidate run; the typed MVP changes one logical axis | Parent run, hypothesis, frozen parameters, metric deltas and decision |
| Change QC, Scrublet policy, cell selection, HVG or Harmony | A distinct scientific experiment outside the four-axis MVP | Changed cell/feature population, explicit rule, config snapshot and newly reviewed clusters |
| MethylVI latent mixing | Diagnose depth, coverage, batch and training before changing the model | Ordinary latent/graph metrics and separate supervised sensitivity plots |

Rendering or relabelling never implicitly authorizes filtering cells. A mixed
label remains a complete, low-confidence proposal when that is the best-supported
call. Do not force a subtype or remove a cluster to make islands look cleaner.

## Continue the authorized loop

1. Establish the selected incumbent and the current candidate from signed run
   evidence, not the latest directory name. Record parameter, code, input,
   annotation and cell-set identities. A computationally complete run may still
   lack a complete annotation or a visually reviewed figure delivery.
2. Diagnose the problem with candidate-marker tables, cell-type/cluster/sample
   UMAPs, QC overlays and high-dimensional neighborhoods. Disconnected 2-D
   islands can belong to a connected graph; connectivity alone also does not
   prove biological equivalence. Examine weak bridges and sample enrichment.
3. State one hypothesis and a bounded candidate set. For the automatic four-axis
   controller, follow [optimization.md](optimization.md) exactly. Keep manual
   scientific experiments in a separate run/session with their actual changes
   recorded; never describe a multi-axis experiment as an MVP single-axis round.
4. Submit through the DAG, inspect completed evidence, then compare to the
   incumbent using the same evaluation neighborhood size, sampling seed, label
   level, palette and panel geometry. Record the evaluation population: if QC
   changed the cell set, report retention and both common-cell and full-cohort
   results where meaningful instead of attributing all differences to layout.
5. Reconcile every new partition against its own markers. An earlier candidate's
   exact-ID labels are a useful proposal reference, but remain dependent evidence.
   Inspect purity, disagreement, rare populations, sample enrichment, doublet
   scores and alternative identities before accepting its labels.
6. Record **retain incumbent**, **select candidate**, **continue diagnostics**,
   **review required**, or **stop without improvement**, with concrete evidence.
   A rejected candidate stays available. A completed job, a model's accept score,
   or an attractive UMAP alone is not convergence or biological approval.
   A material gain cannot cancel an unacceptable loss in another metric. Check
   both incumbent-relative and initial-baseline-relative losses; keep layout-only
   improvements distinct. Numeric tolerances are screening rules, not p-values.
7. If continued iteration was requested, carry on within that scope until the
   configured stopping condition, evidence-supported selection, or a specific
   unresolved scientific choice. Do not repeatedly ask to continue an already
   authorized parameter search. Report the best-supported result even when the
   stopping budget expires without convergence; do not claim a global optimum.

For each round save a compact comparison table containing parent/candidate IDs,
changed parameters, retained cells/features, annotation revision, fixed-k
metrics, batch/QC diagnostics, backend state and final decision. Reference the
actual tables/figures from the stage Report rather than copying implementation.

The 0.12 controller implements an incumbent-centred, non-repeating local search
and writes `selection_summary.json` every round. LLM accept/no-change suggestions
do not terminate available search; escalation does. At completion, name the
incumbent artifact, stopping reason, rejected alternatives and unresolved checks.
Only the selected finalists need more expensive independent seed repetitions;
predeclare seeds and report unstable rare groups, not just mean/global scores.
Do not automatically promote the last candidate or call a budget stop convergence.

## Annotation revisions and downstream handoff

Export each revision into a fresh directory with per-cluster and per-cell tables,
confidence, alternatives, marker evidence, category order, palette and a hashed
manifest. Preserve the source H5AD. If a derived H5AD is needed, verify exact
cell-ID order and cluster assignments against the source, and unchanged counts,
latent/UMAP coordinates and graph. Distinguish a label revision from a new
partition. Display level (broad lineage versus subtype) is explicit metadata.

`tools/prepare_scanpy_candidate_reference.py` converts a run-specific worksheet
into an unapproved exact-ID reference under `Data/`. It checks completed Scanpy
task evidence, source signature, unique cells/clusters and complete mapping,
retains marker evidence, and refuses overwrite. It does not infer labels or
record approval. See [Scanpy](scanpy.md#candidate-reference-tool).

Approval applies to an exact exported annotation revision and its cells. Record
the user's decision and the approved source hash; a filename, a plotting request,
or a project-level flag alone cannot review later revisions. A baseline rerun is
optional if the approved, verified cell table is the intended downstream input.
If requested, run it under a new ID and verify actual membership as well as the
profile signature/cluster set: the same numeric cluster set is not proof of the
same partition. `run_kind`, `iteration_id`, and `analysis_confirmed` are plumbing
fields excluded from the current analysis signature; changing only those fields
does not itself invalidate a mapping. Numerical reruns may nevertheless differ.

For cell-type DMR, materialize a separate reviewed table under `Data/` with exact
ALLC cell-ID coverage, minimum group sizes and an inclusion/exclusion ledger.
Review flags and low-confidence mixed groups need an explicit disposition.
Preflight and MethSCAn reject case-insensitive placeholders, unresolved
`annotation_requires_review`/`requires_review`, unapproved nonempty per-row
`review_status`, and false `dmr_eligible` when supplied. A descriptive label
containing “review” is not itself a machine-readable flag. On user approval,
materialize the new reviewed table with the appropriate row statuses; changing
only the project-level approval cannot clear pending rows. Do not relabel exclusions
as `Unassigned`, or silently include them as a DMR type. Preserve the original
delivery and report removed cells/types. Configure `annotation.table` and its
approval state for this derived input, then validate the selected DMR routes.

## QC and reproducibility diagnostics

- Scrublet's expected-rate prior and its thresholding policy are different
  choices. IPF_final used a rate-quantile threshold in a local experiment; the
  packaged notebook uses Scrublet's automatic calls. Do not silently copy the
  project's rate or quantile policy into the template. Record expected rate,
  actual threshold, predicted/retained counts and score ties for each sample.
- If a Harmony warning is questioned, compare objective trajectory, termination
  iteration, numerical displacement and neighbor preservation before increasing
  iterations. Record library versions, seeds, dtype and threads. Matching seeds
  do not guarantee identical clusters after numerically sensitive initialization.
- Persist verified sample/condition/donor metadata by an explicit manifest join;
  check complete coverage. Report missing group figures as missing metadata.
  The packaged RNA reader transfers manifest `sample_id`, `condition` and `batch`
  to categorical obs; the configured group field uses declared condition.
  Missing values remain missing. Other fields such as donor need an explicit join.
  When condition and data source coincide, batch-mixing metrics cannot establish
  that technical and biological effects have been separated.
- Keep per-sample QC gate counts and overlaps. A threshold that removes no cells
  is not evidence that another gate or a doublet policy is appropriate.

## MethylVI unsupervised iteration

For executable retained-latent screening and the complete feature/model outer
loop read [methylation iteration](methylation-optimization.md). Its separate DAG
route does not invoke the Scanpy controller. The IPF_final custom controllers
must not be copied with monkey-patched validators, run IDs, paths, cell counts
or hardcoded grids.

Start from verified trained-model/embedding artifacts. Audit latent-depth
correlations, observed-feature coverage, sample enrichment conditional on label,
cluster size distribution, label composition, and seed stability. RNA labels are
diagnostic references, not independent ground truth. Use an explicit study-specific
broad-lineage mapping when needed; never infer it from label substrings.

Compare resolution-only candidates on the same graph/UMAP, and neighbors-only
candidates on the same latent representation with other settings fixed. Verify
those reuse claims by hashes/array equality. Resolution can improve a partition
but cannot improve a frozen latent representation; purity alone may reward
overfragmentation. Do not target a predetermined number of clusters. Ordinary
UMAP and supervised target-weight UMAP must retain separate identities; label-
guided separation is not evidence of unsupervised model improvement.

Predeclare screening criteria and search budget for the study. If no candidate
clearly improves the evidence, retain the incumbent and identify the limiting
factor. A changed feature set, latent dimension, training configuration or cell
selection requires its own signed model experiment and input validation.

Use a staged budget: diagnose first; screen graph/resolution settings on verified
retained latents; investigate feature/model changes only if those diagnostics
identify a latent-level defect; confirm a short list across seeds before final
selection. Separate training validation loss/convergence, unsupervised structure,
donor/coverage confounding and supervised-display sensitivity. A lower validation
loss alone is not proof of better cell identity. Compare on fixed overlapping
cells/features or explicitly report why models are not directly comparable.
Reuse count matrices/models only when the relevant inputs, parameters and code
match; a figure-only change never calls for retraining. Independent candidates
may run concurrently within measured node CPU/RAM capacity, without inventing
dependencies. Do not cancel, requeue or modify running model snapshots to apply
a maintenance upgrade. Feature discovery/retraining remains an agent-managed
outer experiment; `methylation_iteration` implements the retained-representation
inner loop, not unattended model retraining.

Reused outputs need source task completion, input/code signatures, cell/feature
identity, parameter compatibility and artifact hashes. Reusing old ALLC evidence
is not full validation of new code/configuration. If the user requests avoiding
another raw-data scan, record the precise reused evidence and any explicit
validation skip; never rewrite old evidence to match the new signature. Figure
source reuse does not itself implement computational cache reuse.

## Backend failures and supplemental reviews

Keep immutable review rounds, including failed API attempts and fallback state.
A network-only retry may read frozen small evidence on the submit host; H5AD
analysis and rendering still use compute resources. Save a retry as a supplemental
record bound to the original evidence hashes. It does not replace an applied
round, lift an escalation, or authorize applying a failed round's fallback.

If a vision service rejects an oversized image, generate a labelled preview copy
or bounded panel crops, recording original and transmitted hashes, dimensions
and transformations. Preserve publication originals. Do not claim visual-model
review when no usable image was transmitted, or treat an optional degraded sensor
as a successful visual review.
