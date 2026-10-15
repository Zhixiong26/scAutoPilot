---
name: scautopilot
description: Create, execute, iteratively review, and plot portable single-cell RNA and DNA-methylation projects with Scanpy/Harmony, MethSCAn, ALLCools, and MethylVI. Use with 10x matrices and indexed per-cell ALLC, including existing-project continuation, candidate annotation and publication figures; not raw FASTQ/BAM processing.
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
| Improve or select an analysis | Read [iteration practice](references/iteration-practice.md). Identify the incumbent, evidence, allowed changes and stopping condition. For the four-axis Scanpy controller also read [automatic review](references/optimization.md). |
| Revise labels or figures | Locate the exact source run and annotation revision. Read [Scanpy annotation](references/scanpy.md) or [publication figures](references/publication-figures.md); reuse saved coordinates for presentation-only work. |
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
The packaged automatic controller changes one adjacent grid step in exactly one
logical axis: PCs, neighbors, resolution or UMAP min_dist. It uses fixed
cell-ID-based sampling and evaluation k across the session. Other scientific
changes require a separately planned experiment and a new session.

Review only completed evidence-valid candidates. Frozen rounds bind the full
configuration and source hashes; applying a round is a separate recoverable,
single-use operation. Escalation overrides automatic acceptance. Stop at the
configured budget, lack of improvement, grid boundary or review requirement;
continuation after a terminal round needs an explicit new session. Automatic
acceptance is neither annotation approval nor proof of global optimality.

An annotation derived from the same clustering is circular evidence, even after
review. Independent cell-type validation requires an explicit independent
reference. Report backend fallback and unavailable visual review honestly:
`system_one_local` simulates the System One interface with an ordinary LLM and
must never be described as Jev. Keep credentials out of evidence and use the
isolated decision environment described in [automatic review](references/optimization.md).

Preserve integer MethylVI `mc`/`cov`, `0 <= mc <= cov`, unique cells/features and
matching input signatures before checkpoint reuse. Keep Top-N hypo-DMR display
selection separate from the all-unique pooled-DMR MethylVI feature route.

## Figure delivery

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
