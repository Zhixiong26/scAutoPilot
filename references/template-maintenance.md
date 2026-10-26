# Template maintenance

Version 0.16.2 permits direct replacement of figures for requested pure appearance
changes. No mandatory new revision or additional approval is needed; scientific
inputs/identities remain unchanged and affected artifact/checksum/visual-review
records must be refreshed. This is a documentation and generated AGENTS policy
update, not a new overwrite CLI flag or an automatic resealing implementation.
Scientific changes still require new results. Existing runtime signatures are
unchanged by this documentation-only release.

Version 0.16.1 fixes candidate annotation delivery: no-reference numerical output
is explicitly `candidate_annotation_incomplete`, placeholder cell-type plots are
suppressed, and the run inspector requests agent completion before delivery.
`complete_scanpy_candidate.py` applies provenance-bound proposals without
recomputing coordinates and exports a derived H5AD plus marker evidence for the
existing embedding renderer. The agent still performs biological interpretation;
no unattended annotation service is claimed. These runtime changes require new
plans; preserve historical and active executors and use a new revision for old
figures. Candidate delivery never grants biological approval.

Version 0.16.0 implements categorized result roots in built-in/custom/QC planners,
submission/execution checks and report links. New tools `result_paths.py` and
`reserve_results.py` are distributed with the generator; generated AGENTS.md
applies path and figure rules to exploration too. Custom plans now require an
explicit category and output arguments use `{result_dir}`. This changes runtime
signatures: freeze a new maintained executor, validate and plan afresh. Do not
patch active/frozen executors or relocate historical results during skill sync.
Existing layout-v1 plan paths remain readable. See [result layout](result-layout.md).

Version 0.15.5 adds four methylome protocol references: atlas/feature roles,
shared-marker selection and presentation, subject-level disease/coupling, and
reference/accelerated benchmarking. Routing and documentation are updated;
no runtime scripts, schemas or automatic disease/benchmark routes are added.
Source, installed and project skill documentation may be synchronized without
replacing any frozen executor. Project-specific scripts with pending validation
are not promoted into portable runtime tools. Existing execution signatures and
historical results are preserved; a future executable adapter requires its own
tests, new runtime and signed plan.


Version 0.15.4 adds `verify_derived_inputs.py`, consumer-side H5AD diagnostics,
producer-scoped dependency validation and regression tests. Distribute the helper
with the renderer and generator; these change execution signatures. Synchronize
source, installed and project skill copies, but preserve frozen historical and
active executors. This release adds explicit checks, not automatic retries or
background repairs.


Version 0.15.3 adds deployed-runtime capability checks at planning/submission,
explicit checksum-bound `derived_artifacts` inputs for custom derived-only DAGs,
and `render_embedding_revision.py`. Scheduler recommendations retain all allowed
healthy partitions that fit the exact allocation, and submission applies node
exclusions. Result indexes now group task inventories under one run page.
Distribute the complete current `tools/` set and `Scripts/Common/` together in
a new frozen runtime; this changes execution signatures. Do not patch historical
plans, relabel old evidence as sealed, or overwrite old figures. The audit tool
checks static wiring, not scientific truth or an arbitrary adapter's compliance.

Version 0.15.2 adds optional `run_methylation_reads_qc.py` and
`plan_methylation_reads_qc.py` runtime tools. This is a pinned-source diagnostic
DAG, not an automatic doublet detector or filtering route. Upgrade idle project
tools, revalidate, and freeze a new run; historical runs remain unchanged.

Version 0.15.1 defines the paired-doublet agent policy in `paired-doublets.md`:
Scrublet/scDblFinder RNA comparison and selection + MethylScrublet by independent capture library, reviewed shared
filtering, and a compact decision table. This is documentation/policy only;
packaged legacy Scrublet notebook execution and config schema are unchanged.
Do not claim an automatic paired detector DAG, modify frozen analyses, or run
early RNA deletion under the new policy. Explicit official-method deployment,
smoke tests and a shared-mask integration are required for production adoption.

Version 0.15.0 adds `bootstrap_acceleration.py`, `run_accelerated.py` and
`run_vmrseq_cpu.R` to generated runtime tools. External packages stay outside the
skill and are inventoried by SHA-256. MethSCAn opt5 CPU uses the existing DAG
through an explicit environment row; Bismark and vmrseq are standalone adapters,
not new default DAG routes. No automatic environment replacement occurs. These
new runtime files change code signatures; upgrade idle projects only, revalidate
and create new plans. Keep active projects and frozen historical runs unchanged.

Version 0.14.1 extends the task completion index hook to handled failures and
explicit cross-project master targets. Distribute `_common.py` and `run_task.py`
together; runtime identity changes require a new plan. Frozen historical runs
remain unchanged. Configure presentation routing in Results/index_targets.json;
test local and master writes before submission. No monitoring daemon is added.

Version 0.14.0 adds the optional `propose_methylvi_trial.py` runtime tool and the
literature-method reference. It uses an isolated optional Optuna dependency;
existing analysis environments/controllers and config schemas are unchanged.
Distribute the tool with the generator for new projects. Copying it to a generated
project changes runtime identity: upgrade idle executors only and make new plans.
The bridge validates protocol/file bindings, not scientific truth or DAG completion;
it never submits, trains, modifies analysis config or approves models. Other
published methods remain explicitly external protocols, not installed adapters.

Version 0.13.0 adds `scautopilot/review/methylation.py`,
`run_methylation_iteration.py`, planner/validator/task-adapter route support and
configurable MethylVI capacity/history exports. Distribute these together with
the existing search module and task evidence helpers. The new route is explicit
opt-in and artifact-only, not a raw-data pipeline or training daemon. Project
schema remains v2; runtime signatures change. Upgrade idle/new runtimes only and
use new plans. Synchronizing skill copies does not upgrade project executors.
Failed iteration directories are preserved and require a fresh run.

Version 0.12.0 changes review selection semantics and adds
`scautopilot/review/search.py`. Distribute it with controller, benchmark, backend,
`optimization_state.py` and `apply_scanpy_round.py`. New round plans are schema v3
with explicit incumbent restoration; complete v2 plans retain their old apply
contract, but old sessions cannot be continued under the new policy. The new
`selection` settings default safely when absent. Project configuration remains
schema v2. Upgrade only idle maintenance roots; if jobs use independent frozen
runtime copies, verify that isolation before upgrading the parent. Never replace
their scripts/config or revise historical hashes. New code requires new plans
and a fresh optimization session; copying the installed skill alone does not
upgrade a generated runtime. The executor still performs full Notebook replay.

Version 0.11.1 adds the fourth DMR heatmap (`zscore_mean.png`) and its support
tables to rendering, task evidence, summaries and comparison collection.
Runtime signatures change. Upgrade only idle projects and create a new plan;
old three-view deliveries remain historical evidence, not four-view deliveries.
Do not modify frozen runtimes of active projects. Configuration stays schema v2.

Keep algorithm scripts in stage directories, remove site paths and sample labels, and route project values through configuration or explicit CLI/environment inputs. Record source-to-template mapping in `migration-inventory.tsv`. Replace static Slurm resources with scheduler profiles.

Two document contracts exist and are not interchangeable. The root `README.md` is written once by `init_project.py` from the intake and the resolved configuration, and is never rewritten with runtime state; the root `Report.md` run log is owned by `build_report_text()` in `tools/_common.py` and grows one record per run. The module documents under `Scripts/<Module>/` follow the same split one level down: the stage READMEs and the prose of the stage Reports are ported verbatim from the template and bound to the project once by `adapt_stage_docs()`, and the stage Reports' run-log regions are written by `refresh_stage_run_logs()`. See [documentation](documentation.md) for the ownership rules and `references/scanpy.md` for why the template's own sample names stay in its prose.

Know what the execution signature covers before copying tools into a live project. `code_signature` hashes `.py`, `.sh`, `.sbatch`, `.R` and `.r` files under `Scripts/` and `tools/`, notebook cell types/sources under those directories, `environment-specs/*.yaml`, and `workflow.py`; markdown files are outside it. Notebook outputs, execution counts and metadata are excluded. Appending to a Report therefore cannot invalidate a recorded plan, but copying newer runtime code or notebook sources changes `code_signature`, which changes `input_signature`, orphans recorded full validations, and prevents an in-flight run from resuming until it is re-validated. Document that consequence in the release notes instead of leaving it to be discovered.

Version 0.11.2 adds `runtime_identity` and `plan_identity_version: 2` to new plans.
Task startup checks the source/config manifest before executing or replacing task
status. Legacy plans remain readable but do not gain this protection retroactively.
Figure delivery hashes the immutable projection of new plans, excluding scheduler
bookkeeping. Existing legacy figure manifests keep their original file-hash rule.
RNA directories now inventory files (resolved path, size, nanosecond mtime/ctime),
not just directory stat; this is metadata identity, not a content-checksum claim.
New task-output records are sealed with artifact identities; legacy records remain
existence-only unless their specialized validator supplies stronger evidence.
Do not manufacture new identity evidence for old files without a separate audit.

Do not package logs, results, checkpoints, notebook output, credentials, Python caches, legacy uppercase `Config`, or dynamic state. The project generator must ignore `__pycache__`, bytecode, test caches, notebook checkpoints, OS metadata, and stale pre-schema-v2 configuration directories even when they exist in the installed skill checkout. Increment `VERSION` for releases and keep schema compatibility within a minor version.

`assets/project-template/Supplementary/` is the one place packaged data is allowed, and only for immutable public reference files that a config key would otherwise force every project to supply — today human hg38 chromosome sizes and the ENCODE GRCh38 exclusion list, both a few kilobytes. A bundled reference must be project-independent, must not name a site, and must be small and public; `Supplementary/README.md` records its source and digests there. Anything study-specific belongs in the intake, never here: a cell-type mapping or a site environment inventory shipped as a default would apply one study's answer to the next project while looking like configuration. `init_project.py` verifies the bundled blacklist against its recorded md5 before defaulting it, so a corrupt install fails at generation instead of writing an unchecked digest into a project.

Input data is never packaged. The template ships the `Data/` convention, not its contents: the generator links declared sources into it, and anything that would make a generated project's `Data/` non-empty is a defect.

The validator currently includes all notebooks under `Scripts/` and `tools/`, including the shipped worked example, using their cell types/sources only. The managed Scanpy task executes `scanpy_workflow.ipynb`; do not describe that notebook as excluded from the execution signature.

Standalone Slurm wrappers are packaged alongside the run DAG so a stage can be explored, smoke-tested, or recovered without a plan. Each wrapper must resolve resources from a named scheduler profile, carry no `#SBATCH` site directive and no absolute site path, and never stand in for a run's completion evidence.

Figure delivery adds signed runtime tools and changes the default DAG. Upgrade only idle generated projects, then plan a new run and validate it. Never modify active/frozen plans in place. Runtime distribution includes figures_comparison_evidence.py and record_figure_review.py; generated projects do not import the installed skill. See [delivery contract](figures-comparison.md).

Version 0.11.0 changes runtime signatures (metadata transfer, annotation gates,
benchmarking and iteration transactions). Include `optimization_state.py` and
the review package when distributing runtime tools. Project configuration remains
schema v2; optimization **round plans** now use schema v2 as a separate artifact
format. Older rounds remain audit records, but the new applier refuses schema-v1
rounds because they lack complete configuration/source bindings. Revalidate the
idle upgraded project, produce evidence under a new plan, and start a new review
session. Do not retrofit hashes or approval into a frozen old round.
