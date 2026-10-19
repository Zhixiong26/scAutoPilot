---
name: scautopilot
description: Create, execute, iteratively review, and plot portable single-cell RNA and DNA-methylation projects with Scanpy/Harmony, MethSCAn, ALLCools, and MethylVI. Use with 10x matrices and indexed per-cell ALLC, including existing-project continuation, candidate annotation and publication figures. Also integrate supplied Bismark, MethSCAn and vmrseq acceleration packages through optional explicit adapters.
---

# scAutoPilot

Build auditable analyses from explicit inputs and preserve the evidence needed to
choose a result. Use the maintained generator and runtime tools; a previous
study supplies lessons, not default sample identities, parameters or approval.

## Start from the requested work

| Request | First action and reference |
|---|---|
| New project | Read [configuration](references/configuration.md), resolve intake metadata and inputs, then use `scripts/init_project.py` in an empty destination. |
| Continue or diagnose an existing project | Read its configuration, stage Reports, selected run plan and completion evidence. Use its bundled `tools/`; do not regenerate the project. Read [execution](references/execution.md) or [troubleshooting](references/troubleshooting.md) as needed. |
| Improve or select an analysis | Read [iteration practice](references/iteration-practice.md). Identify the incumbent, evidence, allowed changes and stopping condition. For Scanpy read [automatic review](references/optimization.md); for MethSCAn/MethylVI read [methylation iteration](references/methylation-optimization.md). For published alternatives or confirmatory methods, read [literature-backed methods](references/published-methods.md). |
| Revise labels or figures | Locate the exact source run and annotation revision. Read [Scanpy annotation](references/scanpy.md) or [publication figures](references/publication-figures.md); reuse saved coordinates for presentation-only work. |
| Use supplied acceleration software | Read [acceleration backends](references/acceleration.md). Stage and verify the supplied releases, provision isolated dependencies, then choose the MethSCAn backend or an explicit Bismark/vmrseq invocation. |
| Maintain this skill or upgrade templates | Read [template maintenance](references/template-maintenance.md). Update the portable template and distribution, test in isolation, and explain signature changes before upgrading an idle generated project. |

Read only the workflow references involved: [Scanpy/Harmony](references/scanpy.md),
[MethSCAn](references/methscan.md), or [ALLCools/MethylVI](references/methylvi.md).
Existing authorization carries forward within its scope; this skill itself does
not authorize execution, annotation approval, or unrelated experiments.

## From inputs to completed evidence

1. Resolve inputs through the project's `Data/` links or verified downloads and
   explicit sample manifest. Keep RNA, ALLC, annotations, genome files and shared
   environments read-only. Each indexed ALLC needs its adjacent `.tbi`; derive
   ownership from `samples.tsv`, chromosomes from `chrom_sizes`, and contexts
   from configuration. Never infer condition, batch, donor or cell identity from
   directory names. Preserve declared checksums, including local-file sources.
2. Discover compatible environments before creating missing isolated ones. Read
   [environment provisioning](references/environments.md); never upgrade a shared
   environment to make this project run.
3. Validate the selected routes with `tools/validate_project.py`. Quick validation
   precedes planning and submission; first production use or changed inputs,
   schema or runtime requires matching full-validation evidence. Full ALLC
   validation reads inputs in distributed compute jobs. The explicit
   `--skip-full-validation` option records missing evidence, not a passing check.
4. Plan a distinct DAG with `tools/plan_workflow.py`. Outputs belong in
   `Results/runs/<run-id>/`; reuse an ID only to resume its matching signed plan.
   For authorized execution, inspect scheduler resources immediately before each
   submission. Never execute a planned task on a Slurm submit host.
   Run analysis and numerical review on compute nodes, or on a standalone machine
   without a scheduler. On a submit host, obtain an allocation;
   do not bypass execution guards. Follow [execution](references/execution.md).
5. Use validated artifacts, task completion markers and `run_summary.json` to
   determine completion. Submission success and Slurm exit state are insufficient.
   Execute production tasks through the planned DAG; custom tasks must emit
   `task_outputs.json` with existing artifacts. Standalone wrappers support
   exploration, isolated smoke tests and recovery, not DAG completion evidence.
6. Report the selected result, unresolved decisions and evidence paths. Keep the
   generated root README stable. `inspect_run.py` refreshes root/stage Report run
   logs; `update_report.py` rebuilds them. Read
   [documentation](references/documentation.md) when changing these contracts.

Respect task resource floors; do not pin nodes without a data/hardware need.
Report reserved CPU/memory separately from measured load and free memory. Use
isolated smoke tests after runtime, environment or high-risk route changes.
Preserve active frozen runtimes during upgrades. New plans verify executable and
configuration identity at task start, without rereading full ALLC inputs. A busy
but capable healthy node may queue work; independent models need no artificial
scientific dependency. Follow the signed output and recovery contracts in
[execution](references/execution.md), including idempotent result-index updates.

## Annotation and iterative decisions

A Scanpy candidate needs a complete proposed annotation. Match a supplied
per-cell reference by exact cell ID; otherwise use this run's markers, QC, sample
composition and appropriate biological references. Record confidence,
alternatives and marker evidence, render the annotated candidate, and then
request the user's review. `Unassigned` is not a finished candidate annotation.
`tools/prepare_scanpy_candidate_reference.py` packages a completed run's worksheet
as an unapproved, provenance-bound reference; it does not grant approval.

Never transplant numeric cluster mappings. `tools/record_annotation_review.py`
binds a mapping to the source analysis signature and exact cluster set. Bind
approval to the actual exported revision and cells; a numerical baseline rerun
must also verify membership. An explicitly approved, verified derived cell table
can feed downstream analysis without a baseline rerun.

Cell-type DMR additionally requires approved project-level annotation, sufficient
group sizes and resolved per-row review/eligibility flags. Case-insensitive
placeholder labels are rejected. Descriptive labels alone cannot communicate a
review decision: retain confidence, exclusions and explicit disposition in a
separate handoff table. `analysis.methscan.use_rna_annotation: false` defers RNA
annotation and leaves unsupervised VMR available while disabling cell-type DMR.

For continued improvement, distinguish scientific changes, annotation revisions
and rendering revisions. Keep the incumbent explicit and retain rejected runs.
The Scanpy automatic controller searches around the selected incumbent, not
the latest run. Each candidate changes one adjacent grid step relative to that
base: PCs, neighbors, resolution or UMAP min_dist. Restoring a rejected candidate
to its incumbent is explicit in the plan. Science/partition search precedes
layout search; repeated settings are skipped. Fixed cell/feature identities,
sampling, evaluation k and a frozen baseline space make comparisons auditable.
Other scientific changes require a separately planned experiment and a new session.

Review only completed evidence-valid candidates. Frozen rounds bind the full
configuration and source hashes; applying a round is a separate recoverable,
single-use operation. Model acceptance is advisory, never an automatic pass.
Retain the incumbent on material regression or incomplete metrics; record the
best-supported result even when the budget expires. Try other unvisited legal
candidates at a grid boundary. Stop at the declared budget, exhausted local
search or escalation; a terminal round needs a new session. Confirm finalists
with marker/QC/rare-population review and seed stability, followed by explicit
annotation approval. Do not claim global optimality or checkpoint reuse that
the executor has not implemented. See the exact policy in optimization.md.

An annotation derived from the same clustering is circular evidence, even after
review. Independent cell-type validation requires an explicit independent
reference. Report backend fallback and unavailable visual review honestly:
`system_one_local` simulates the System One interface with an ordinary LLM and
must never be described as Jev. Keep credentials out of evidence and use the
isolated decision environment described in [automatic review](references/optimization.md).

Preserve integer MethylVI `mc`/`cov`, `0 <= mc <= cov`, unique cells/features and
matching input signatures before checkpoint reuse. Keep Top-N hypo-DMR display
selection separate from the all-unique pooled-DMR MethylVI feature route.

MethSCAn/MethylVI have a separate `methylation_iteration` DAG route for verified
retained representations. Screen graph/partition before layout; never truncate
MethylVI latent axes as PCs. Retained-PC MethSCAn screening does not recompute
imputation/PCA. Feature/model changes require a separate agent-managed experiment;
DMR significance is not an optimization objective. Read
[the complete loop and reuse boundaries](references/methylation-optimization.md).

Prefer established, applicable methods when local screening is insufficient:
chooseR for resampling robustness, clustree for resolution diagnostics, scIB for
integration assessment, and Optuna for outer model proposals. Read
[method-specific contracts](references/published-methods.md) first. Record official
versus adapted execution, dependencies and evidence; existing seed checks and
approximate mixing scores must not be renamed as these methods. The optional
`propose_methylvi_trial.py` bridge calls official Optuna but never trains, submits
or approves a result. Other external methods need separate deployment. Do not
optimize circular label agreement, disease mixing, DMR significance or plot beauty.

## Figure delivery

After every task finishes (including handled failures and recovery), update
`Results/RESULTS_INDEX.md` without waiting for a separate user request. Before
submitting a new run, verify its frozen executor contains the completion index
hook; skill text alone is not automation. If the user names a cross-project
master index, configure its parent in `Results/index_targets.json` and smoke-test
both local and master publication. Include verified existing figure/preview paths, source
run and analysis identity, and separate artifact and visual-review states.
Index a completed branch even if sibling tasks are still running. Do not claim
background auto-refresh unless a real scheduled completion hook exists.
See [result-index rules](references/documentation.md#results-and-figure-index).

Every methylation DMR heatmap delivery (per sample or pooled) includes four views:
raw mean ratio, DMR-wise Z-score, display-compressed Z-score, and cell-type mean
of saved single-cell Z-scores. Keep support counts and missingness; never
re-standardize group means or treat this as donor-level inference. See
[publication figures](references/publication-figures.md) for the exact contract.

For plot-only requests, preserve source H5ADs, saved coordinates, scientific
parameters and annotation revisions. Freeze category order/palette, verify source
hashes and export a new figure revision. Read
[publication figures](references/publication-figures.md) for expression scales,
composition denominators, DMR missingness/normalization and visual acceptance.

Every individual embedding uses `Scripts/Common/embedding_plot.py` and
`save_embedding()`: 8 × 8 inches, 300 dpi PNG (2400 × 2400 pixels), equal-aspect
square axes, categorical legend outside the panel in one column, and a vertical
numerical color bar. No tight cropping. Split overcrowded comparisons into
individual panels. Dotplots and heatmaps need not be square.

Selected routes receive a comparison delivery before the workflow summary.
Read [batch figure delivery](references/figures-comparison.md) for source adapters,
checksums, recovery and review. Atlas canvases are the explicit non-square
exception; their individual embedding exports retain the shared standard.
Preserve saved display order and colors across independent renderers.
Artifact completion and visual approval are separate evidence states.

Read [Git collaboration](references/git.md) only for requested repository actions.
Generated projects carry their runtime tools and do not depend on this skill
remaining installed.
