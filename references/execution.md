# Scheduler and execution

`plan_workflow.py` writes a closed DAG under `.workflow/runs/<run-id>/`; writable analysis outputs go to `Results/runs/<run-id>/`. `submit_workflow.py` revalidates signatures, requires matching full validation, and resumes only incomplete tasks.

Run `audit_runtime.py --project PROJECT` before copying a legacy executor. New
planner/submission entrypoints refuse missing completion-index or artifact/runtime
identity wiring. Reuse scientific outputs with their source evidence in a new
maintained runtime rather than inheriting an old controller's monkeypatches.
Keep configured project identity and canonical output project consistent; frozen
runtime paths under `.workflow/run_projects/` are implementation locations, not
separate biological projects. Custom task commands write under the plan's
`result_dir`, and emit the same `task_outputs.json` as built-in tasks.

For Slurm, every task independently queries `sinfo`, `scontrol show nodes`, and `squeue` immediately before `sbatch`. Allocation capacity uses `CPUTot-CPUAlloc` and `RealMemory-AllocMem-headroom`; `CPULoad` and `FreeMem` are diagnostic only. The balanced selector requests the target when it fits and may reduce toward the floor. If no current slot fits, `queue_when_busy` (default true) permits a request fitting an allowed healthy node's total capacity and marks `immediately_available: false`. Down/drained nodes are excluded. Set this option false to require current capacity. Observed snapshots are never rewritten to pretend resources are idle.

Dry-run writes `plan_preview.json`, `submission_preview.json` and resource previews;
it does not change the signed plan or live submissions. Resume repairs scientific
dependencies of pending children when a parent job ID changes; running children
with changed parents require manual review. Concurrency limits use `afterany`,
scientific dependencies use `afterok`. VMR+DMR models share completed counts and
their own VMR features, not the preceding model's success.

Resource options and dependencies are passed on the `sbatch` command line. Nodes are not pinned unless a profile explicitly requires it.
`eligible_partitions` lists allowed healthy partitions that fit the selected CPU
and memory allocation; submission passes this list directly to Slurm. The selected
reference node remains diagnostic. Node exclusion/allow lists are enforced in the
submission as well as in selection. Avoid post-submission partition rewrites or
replacing the resource selector with a study-specific fallback.

## Host roles

Where a task may execute is a property of the host, and it is the one policy a config file cannot state: a project that declares `backend: local` while sitting on a cluster login node would still run its tasks on that login node. Every decision point resolves the same role through `_common.host_role()`.

| Role | Decided by | Local execution |
|---|---|---|
| `compute` | `SLURM_JOB_ID`/`SLURM_JOBID` is set: we are inside an allocation | Legitimate — the executor is itself on a compute node |
| `submit` | No allocation, and `scontrol ping` reports a controller `is UP` | Not used: the run is promoted to Slurm |
| `standalone` | No allocation and no controller answers | Legitimate — there is no other host to submit to |

`scontrol ping` is the probe rather than `sinfo` or `squeue`. Slurm client commands on PATH prove nothing, `squeue -u $USER` prints nothing and exits 0 on a laptop and on a login node alike, and a controller that answers but is `DOWN` refuses every submission — so the reply itself has to report UP, not merely arrive.

A `local` project on a submit host is **promoted to Slurm**, not refused and not executed in place. The promotion is recorded: `submissions.json` carries `backend_declared` beside `backend_effective`, each `resource_snapshots/*.json` carries `host_role`, and every `task_status.json` records the role and `slurm_job_id` the task saw. A promotion needs a partition allow-list; when `scheduler.partitions` is empty it refuses and names the partitions `sinfo` reports.

**A planned task is never executed on a submit host.** The guard is at execution rather than at planning: `Scripts/Common/run_task.py` refuses before it reads a plan or creates a task directory, and `Scripts/Common/task_adapter.py` refuses before it runs a stage, because a hand call to either is a separate entry point. `Methylvi/*/run.sh` carry the same refusal in shell. A refusal is a precondition failure, not a task result: it exits 2, writes no `task_status.json`, and cannot be mistaken for a failed attempt. The legitimate work of a login node is planning, validation, submission, inspection, and reporting — including the `sinfo`/`squeue` queries the resource check performs.

The one exception is explicit and run-scoped. `submit_workflow.py --allow-login-execution` names a single run, is passed to the task as `SCMO_LOGIN_EXECUTION_ACK=<run-id>`, and is honoured only when that value equals the run being executed, so it cannot carry over to the next run. It is never inherited by a submitted job or written into `os.environ` — an inherited bypass would disarm the guard in the very child process it exists to constrain. Every task it covers is recorded as `login_execution: true`. Prefer the alternative it stands in for: run the orchestrator inside an allocation (`salloc`, or `srun --pty bash`), where the role is `compute` and the local executor is on a compute node.

Resource inspection for the `local` backend is against the local machine: the recommendation is the profile target clamped to `scheduler.local.max_threads`/`max_memory` and floored against the profile, and no cluster is queried, because none is involved. A snapshot whose `backend` is `local` therefore reports `nodes: []` by design, and says so in its `note`.

Built-in adapters cover every planned task and choose the task's declared stage Python from `environments.tsv`. The task registry is checked during planning and again before production submission. `analysis.task_commands` may override an exact or prefix-wildcard task and may use `{python}`, `{project}`, `{run_id}`, `{run_dir}`, `{result_dir}`, `{task}`, `{task_dir}`, `{threshold}`, and `{features}`.

After a successful override, write `<task_dir>/task_outputs.json` as a JSON object with a non-empty `artifacts` list. Artifact paths should be absolute and every path must exist. The wrapper stores the child command's code as `process_return_code`; missing or invalid evidence makes the wrapper `return_code` nonzero with `failure_stage: output_validation`.

The successful wrapper seals new artifact records: regular files carry size and
mtime, and files up to 16 MiB also carry SHA-256. Large files still require producer
format/count checks; directories receive presence/type checks, not recursive
content validation. Empty scientific files are refused unless explicitly listed
in `allow_empty_artifacts`; `.COMPLETE` markers may be empty. Prefer header-bearing
zero-result tables and explicit no-result JSON. Old unsealed records are not
retroactively content-verified. Custom workflow summaries have the same default
task_outputs contract as other overrides.

After successful verification, run_task updates Results/RESULTS_INDEX.md in a
locked, atomically replaced, run/task-keyed block, preserving human-written text.
An index failure is a separate warning and never a reason to repeat science.
Memory inspection retains sacct steps and reports the maximum recorded task RSS
with its source; this is not simultaneous whole-job RSS. Running accounting is
provisional, not evidence of zero CPU use.

Production stages are entered through `plan_workflow.py` and `submit_workflow.py`. The template also ships standalone `run_*.sbatch` and `submit_*.sh` wrappers for exploring one stage, smoke testing a change, and recovering a single stage of a completed run. They are not a second production path: they produce no `task_outputs.json`, carry no site directive, and take their resources from the same named scheduler profiles the DAG uses, so a wrapper run and a DAG run request identical allocations. A wrapper's success is a stage result, never a run's completion evidence.

The MethylVI route runners (`Methylvi/allcools/run.sh`, `Methylvi/vmr/run.sh`) refuse to start without a managed run ID, because a stage run outside the DAG cannot contribute completion evidence. The packaged wrappers that invoke them set `SCMO_STANDALONE_ACK=1` to acknowledge that explicitly, which is why they work standalone and also print a warning that no completion evidence is recorded. Calling `run.sh` directly still requires either a managed run ID or that acknowledgement; it is never granted implicitly. That acknowledgement says a run may bypass the DAG and says nothing about which host may execute it, so on a submit host a direct call is refused as well.

The packaged `run_*.sbatch` wrappers are sbatch entry points: `submit_*.sh` submits them, and the DAG reaches them from inside an allocation. They are `bash` scripts with no execution guard of their own, so `bash Scripts/Methscan/run_methscan_common.sbatch OUT` on a login node would run that stage in the caller's process. Submit them; do not source or bash them by hand outside an allocation.

Slurm requires a non-empty partition allow-list. Every dependency must exist in the plan; unknown dependencies are fatal. A scheduler `COMPLETED` state is not completion without valid status, signature, marker, and artifacts.

Inspecting a run also refreshes that run's record in the root Report's run log. That write is best effort and never affects the run's verdict: the exit code of `inspect_run.py` reflects the run's state, so an unwritable Report is reported on stderr with the recovery command and leaves the code alone. Use `tools/update_report.py` when the write must fail loudly, or to rebuild the whole log after pruning, migration, or hand edits. See [documentation](documentation.md) for the region format.

Before a run can read its inputs, they have to be where it expects them. Generation links each declared `data.sources` entry into `Data/`, and `tools/link_data.py --project PROJECT --execute` performs the downloads it left pending, verifying each against its declared sha256. Validation refuses any entry that does not resolve from the machine it runs on, so check data reachability in the execution context rather than on the login node. See [configuration](configuration.md) for the block's schema.

Provisioning and integrity work is not a planned task and is not covered by the execution guard: `validate_project.py --mode full` reads every ALLC file end to end, `bootstrap_environments.py --execute` solves and creates environments, and `link_data.py --execute` transfers downloads. Each runs where it is invoked, because each has to — an environment belongs in the prefix it creates, and a data check has to see the filesystem the run will see. On a site that forbids such work on a login node, run those three inside an allocation. Their results are not a run's completion evidence either way.

A full ALLC validation is the exception to that, because reading a terabyte of ALLC files is not login-node work. It enumerates the files, splits them into byte-balanced chunks, submits one chunk job per chunk, waits, and merges the results; the reading happens on compute nodes. Enumeration, submission, and merging stay on the submitting host, which is the login-node work the rules already allow. The merge is fail-closed: a chunk that is missing, unreadable, built from a different manifest, or that does not account for exactly the files it was handed makes the whole validation invalid and names the chunk, so a partial read can never pass as a complete one. Chunk results whose manifest still matches are reused instead of resubmitted, so a failed chunk does not cost the whole read. Where there is nothing to submit to, or the project is small, the same check runs in place through a process pool. `--skip-full-validation` on `submit_workflow.py` submits without that evidence when none is on disk, records `full_validation_skipped: true` on the plan and on every task record, and writes no evidence file; evidence already on disk and matching the input signature is used either way. `inspect_run.py` reports the evidence state and the ALLC counts beside the verdict, because a full validation of a project whose selected routes include no methylation reads no ALLC file at all and would otherwise look the same as one that read all of them. See [configuration](configuration.md) for the knobs.

For an explicit custom adapter use `plan_custom_workflow.py --project PROJECT
--spec PROJECT/config/custom_tasks.json --run-id RUN`, then ordinary
`submit_workflow.py`. The JSON list uses `task()` fields (`name`, `profile`,
`dependencies`, `parameters`, `environment`, optional `outputs`). Commands must
be implemented through `analysis.task_commands`; resource profiles must exist.
The task specification is frozen in config and signed with the runtime. This
planner does not monkeypatch route selection or implement an analysis method.

## Derived model recovery

A training-only smoke test does not validate the serializer/reader boundary. Before
rendering, comparison or weighted embeddings, run a read check on the actual H5AD
in the consumer environment on compute. Inspect producer and consumer Python,
AnnData and Scanpy versions. A reader lacking `nullable-string-array` support is
a compatibility failure, not failed model training. Prefer a compatible existing
environment; otherwise create a separately hashed conversion and verify IDs,
integer layers, latent values, graphs, labels and saved coordinates. Do not modify
source H5ADs or upgrade shared environments in place.

`tools/verify_derived_inputs.py` is an optional custom DAG gate. Its spec has a
`sources` list; each entry declares `path`, `sha256`, `run_dir`, `task_id`, and
optionally `format: h5ad`, `expected_cells`, `required_obsm`. Invoke it in the
**downstream consumer environment** with `--spec`, `--output`, `--task-dir`. It
checks artifact ownership, signatures and the named producer's transitive
dependencies. Unrelated failed rendering siblings must not block a completed
model; failed actual ancestors still block. This tool does not poll, retry, train,
convert files, or validate scientific suitability automatically.

For count-cache recovery, `done` flags or successful process exits alone do not
prove row content. Investigate invalid posterior priors against raw counts before
excluding cells. If recomputation contradicts zero cache rows, rebuild affected
rows in a new run, verify normal-row controls and independent interval queries,
and preserve the original cohort unless a justified QC decision says otherwise.
Checkpoints should publish verified chunks atomically, or flush/verify data before
publishing completion markers. An interruption must not make a completion flag
more authoritative than the stored counts.
