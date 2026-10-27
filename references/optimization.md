# Evidence-gated Scanpy parameter search (0.12)

For published alternatives and confirmatory methods, read
[literature-backed methods](published-methods.md): chooseR, clustree and scIB have
distinct purposes and explicit external deployment status. They do not silently
replace this controller's frozen four-axis policy. Its silhouette/DB screen is a
heuristic; missing biological/stability evidence still prevents formal acceptance.

For MethSCAn and MethylVI use [methylation iteration](methylation-optimization.md):
an executable retained-representation DAG loop plus agent-managed outer feature/
model experiments. The Scanpy controller below is not their executor.

For the broader diagnostic/annotation/selection loop and MethylVI comparisons,
read [evidence-led iteration](iteration-practice.md). This controller implements
only the four axes below. User-directed changes to QC, cell selection, HVG or
Harmony belong to a distinct scientific experiment, not an undocumented extra
axis in an immutable MVP session.

This mode reviews a completed Scanpy candidate, records five typed judgments,
and freezes at most one parameter change. It never lets a model author Python
or silently mutate a completed run.

## Authorized search space

The four logical axes and frozen grids are in `config/optimization.yaml`:

- `n_pcs`: 20, 30, 40, 50, 60. This is one logical axis that sets both PCA
  capacity (`pca.n_comps`) and PCs consumed by the neighbor graph
  (`neighbors.n_pcs`) in the next candidate.
- `n_neighbors`: 10, 15, 20, 30, 40, 50.
- `resolution`: 0.4, 0.6, 0.8, 1.0, 1.2.
- `min_dist`: 0.1, 0.3, 0.5, 0.7, 0.9.

Keep UMAP spread, the global random seed, Euclidean distance, batch-correction
configuration, and HVG configuration fixed. A round moves one adjacent grid
step relative to the selected incumbent; it never invents a continuous value or
changes two scientific axes relative to that base. If the latest candidate was
rejected, schema-v3 plans explicitly restore the incumbent first. This may
change several settings relative to the latest rejected run; the restoration
and the one-axis experiment are recorded separately, never hidden.

## Evidence and judgments

`tools/review_scanpy_iteration.py` computes:

- UMAP reviewer: trustworthiness and KNN preservation.
- Clustering screen: silhouette and Davies–Bouldin, full-cohort cluster sizes,
  small-cluster cell fraction, and independent-label best-cluster F1 when available.
- Diagnostics: cell-type ASW, fixed-k inverse-Simpson sample mixing, and batch
  ASW. The historical `ilisi` field is an unweighted fixed-k approximation,
  **not scIB's perplexity-based iLISI**. It is not a selection objective.

An automatic candidate annotation derived from the same Leiden partition is
marked circular. Its cell-type ASW is recorded for audit but cannot serve as
independent biological validation. Only an approved independent annotation can.
The H5AD must explicitly set `uns['annotation_reference_independent'] = true`
and `uns['annotation_status']` to `approved` or `reviewed`; approval alone does
not establish independence. Circular cell-type ASW cannot reset the controller's
no-improvement streak.

The benchmark defaults are `max_cells: 5000`, `evaluation_k: 15`, and `seed: 0`
under `scanpy_mvp.benchmark`. Cells are selected and ordered by a seeded SHA-256
of cell ID, so reordering an H5AD does not change the comparison. Evaluation k
is independent of the candidate graph's `n_neighbors` and is capped for small
datasets. The protocol, complete cell/feature sets, sample/condition metadata,
independent reference labels and sampled-cell digest must match throughout a
session. All candidates are evaluated against the initial run's frozen Harmony
space and its initial `n_pcs`; reference coordinates are hashed. This prevents
a PC change from changing the ruler. The candidate's own Harmony space is used
for batch diagnostics. The initial reference is not biological ground truth:
these scores measure fidelity to that reference, and can miss useful new axes.
Use marker/QC review and finalist stability checks before scientific acceptance;
if the reference itself is unsuitable, start a separately declared experiment.
Unavailable PCs raise an error rather than silently clipping the request.
The 5,000-cell cap bounds the quadratic trustworthiness calculation; increasing
it requires an appropriately sized compute allocation.

The backend must answer a fixed schema: Accept (`Noul`), next parameter
(`Choice`), direction (`Choice`), quality (`Score`), and escalation (`Noul`).
The default development backend is the official
[`system-one-adapter`](https://github.com/typesafe-ai/system-one-adapter-python)
with a local OpenAI-compatible chat endpoint. It is not Jev: it uses an ordinary
LLM to implement the System One question interface.

Set `scanpy_mvp.decision_backend.system_one_local.base_url` and `model` in
`config/optimization.yaml`. The maintained configuration uses
`api: chat_completions` and `structured_outputs: false`; the adapter therefore
puts the output schema in the system prompt, parses the chat model's JSON text,
validates it, and performs bounded corrective retries. Qwen, Llama, DeepSeek,
or another ordinary chat model can be served by vLLM. The endpoint service runs
as a separate GPU/Slurm workload; the reviewer only connects to it.

`system-one-adapter==0.2.1` requires Python 3.10 or newer, so it lives in the
isolated `decision` environment rather than the Python 3.9 Scanpy environment.
Provision it with `tools/bootstrap_environments.py`; the reviewer resolves the
`decision` row in `config/environments.tsv`. Never install it into a discovered
shared analysis environment.

The backend records adapter version, token totals, latency, retry counts, and
the complete adapter response including `llm_attempts` in `backend_audit.json`.
Credentials are read from environment variables and are not written to audit
files. `system_one_commercial` uses the same adapter with OpenAI, Anthropic,
Gemini, or a paid OpenAI-compatible endpoint. For the latter, set
`provider: openai_compatible`, `base_url`, `model`, and `api_key_env`; the
credential is read only from that environment variable and is never persisted.
`typesafe_jev` is a separately named future backend; local adapter results must
never be labelled as Jev. When the configured backend is absent or
fails and fallback is allowed, the result explicitly says
`uncalibrated_rule_fallback_v0`.

## Optional multimodal visual sensor

`scanpy_mvp.visual_review` controls a bounded visual-evidence branch. It is
enabled by default with an explicit non-blocking fallback: when the API key or
service is unavailable, the evidence state records `degraded` and never claims
that a model call occurred. The reviewer collects at most four fixed PNG artifacts from the same
candidate iteration: cell-type UMAP, Leiden UMAP, and one available candidate
marker dotplot. Every file is recorded with its SHA-256, dimensions, and size.

The `openai_compatible` backend sends those images to a separately configured
vision-capable model. The shipped template targets DeepSeek's current
`deepseek-flash` multimodal model at `https://api.deepseek.com`; its legacy
`deepseek-v4-flash-vision-exp` name is not needed. Set `DEEPSEEK_API_KEY` in
the execution environment and change the endpoint/model only when selecting a
different OpenAI-compatible vision service. Credentials are read only from
`api_key_env`. The model
may report only the closed observation vocabulary: sample-specific islands,
disconnected same-label regions, bridge patterns, extreme crowding, isolated
outlier islands, and possible overfragmentation. It cannot score, accept,
reject, or propose parameters.

Each observation is checked against deterministic measurements from the same
candidate H5AD. The result is `confirmed`, `refuted`, or `unverified`; bridge
patterns deliberately remain unverified until a defensible numerical detector
exists. The complete record is frozen as `visual_review.json`, while its
observations, verification, and metrics enter `state.json` under `visual`.
If the visual backend is optional and unavailable, the state says `degraded` or
`unavailable`; if it is required, the round fails closed before publication.
With `enabled: false`, neither image collection nor visual metric calculation
runs. Optional image/metric failures also record degradation instead of silently
claiming successful visual verification.

Every artifact the sensor receives is drawn under the embedding-panel standard
in `references/scanpy.md`: the same 8 × 8 in square exported canvas, 4.0 in single
panel, single-column legend and the same colouring convention in every round.
Comparison overviews use smaller square panels; compare matching layouts.
Recorded dimensions are therefore comparable across
rounds, and a reported shape is never an artefact of a point cloud stretched
into a non-square axes box.

The immutable round is stored under
`.workflow/optimization/<session-id>/round_NNN/` with state, questions,
judgments, `backend_audit.json`, decision, and a signed frozen round plan. From round two onward the
state includes the previous parameter change and per-metric deltas. A new run
whose parameters do not match the preceding frozen plan is refused.
The reviewer rechecks completion evidence and matches current resolved analysis
parameters to the completed run. The session fixes scientific settings, runtime
code, optimization policy and evaluation protocol. JSON and YAML configuration
are both supported. Publication uses a session lock and an atomic directory
rename; a failed review leaves no partially published `round_NNN`.

## One iteration

After a candidate run is complete and `inspect_run.py` has produced valid
evidence, use the project's Scanpy/analysis environment (it must provide
AnnData, NumPy, and scikit-learn) in a compute allocation on Slurm sites:

```bash
"$PYTHON" "$PROJECT/tools/review_scanpy_iteration.py" \
  --project "$PROJECT" --run-id candidate-000 --session-id scanpy-mvp-001
```

If the result is `next_candidate`, materialize the frozen change separately:

```bash
"$PYTHON" "$PROJECT/tools/apply_scanpy_round.py" \
  --project "$PROJECT" --session-id scanpy-mvp-001 --round-id round_000 \
  --next-run-id candidate-001

"$PYTHON" "$PROJECT/tools/validate_project.py" --project "$PROJECT" --mode quick
"$PYTHON" "$PROJECT/tools/plan_workflow.py" \
  --project "$PROJECT" --routes scanpy --run-id candidate-001
"$PYTHON" "$PROJECT/tools/submit_workflow.py" \
  --project "$PROJECT" --run-id candidate-001
```

Do not apply a `review_required` or `stopped` plan. Applying is single-use,
checks the plan digest and config drift, saves before/after configuration
snapshots, and does not itself execute or submit work. Continue the loop only
after the next run has complete validated evidence.

Round-plan schema v2 freezes the complete analysis configuration, optimization
configuration and source hashes. Changes outside the chosen axis are refused,
including otherwise valid edits made after review. Application holds project
and session locks, records `apply_pending.json` before changing configuration,
and writes `applied.json` on success. If interrupted, repeat the same command
with the same `--next-run-id`; recovery verifies the original snapshots and
accepts only the exact before/after configuration. Once complete it cannot be
applied again, and an existing run ID cannot be reused for a new candidate.

## Incumbent selection, search order and stopping

The model's accept probability is advisory. It cannot mark a result accepted,
terminate available search, approve annotation, or compensate for a regression.
The old `policy.accept_threshold` field remains readable for compatibility but
does not control stopping. Escalation still stops immediately for review.
The legacy `stopping.metric_epsilon` is also superseded by the explicit
`selection` tolerances; it no longer resets patience on any single-metric gain.

1. Compare each candidate to the **selected incumbent**, not just the preceding
   run. A candidate needs a material gain and no missing required metric or
   unacceptable loss. Compare against the initial baseline as well, to prevent
   many small tolerated losses accumulating into a large regression.
2. `selection` defaults: absolute metric tolerance 0.01, relative DB tolerance
   0.05, minimum improvement 0.005, small-cluster-cell-fraction increase 0.02,
   and independent-label best-cluster-F1 loss tolerance 0.05. Small clusters
   have fewer than `max(10, ceil(0.001 * n_cells))` cells. These are configurable
   **screening tolerances, not statistical significance or universal biology**;
   freeze them before searching. Flagging small groups is not permission to
   delete a rare population.
3. First search PCs, neighbors and resolution. Require a silhouette/relative-DB
   gain without unacceptable embedding or rare-label degradation. Then search
   `min_dist`; only this phase may select a layout-only gain, explicitly labelled
   as such. Neither global batch mixing nor circular annotation ASW can win a
   candidate. Fallback no longer assumes low silhouette means more clusters.
4. Try legal adjacent settings around the incumbent; consult the model for
   ordering, but skip visited/infeasible settings and try another direction or
   axis at a boundary. Without a usable proposal, try resolution, neighbors,
   then PCs (lower recomputation scope first). No automatic grid expansion.
5. Defaults remain at most 20 evaluated rounds and patience 5. Science patience
   applies only after at least one trial of every feasible scientific axis;
   exhausting the local frontier or the patience budget advances to layout.
   Layout exhaustion/patience or the total budget stops the search. Budget
   exhaustion is **not convergence**; local exhaustion is **not a global optimum**.
6. Every round exports `selection_summary.json` and a machine-readable search
   record with the incumbent run/parameters, comparison, phase, skipped settings,
   counters and outstanding finalist checks. The newest run is not implicitly
   selected. Stopping does not rewrite `analysis.yaml` to the winner or overwrite
   outputs: use the recorded incumbent artifact and a new plan for any rerun.

New round-plan schema v3 binds `base_run_id`, base parameters, PCA capacity and
the base-state digest. Application checks those identities, restores only the
four searched settings/PCA capacity, and makes one adjacent change. Its
before/after transaction remains recoverable. Complete schema-v2 plans can still
be applied under their original one-axis contract; legacy sessions cannot be
continued with the new selection policy. Start a new session and plan.

`execution_scope` records the minimum affected stages. The portable executor
currently does **full notebook replay**: this field is not a checkpoint cache.
Already achieved efficiency improvements are bounded local search, no repeated
parameter points, shared nearest-neighbor calculations and capped deterministic
benchmark samples. Do not claim QC/PCA/training reuse unless a separate runner
actually verifies source signatures and implements it.

Before delivery of the selected finalist, review its markers, rare populations,
sample/condition/QC structure and final figures, and compare alternate seeds on
the same cells. Separate these confirmatory runs from the fixed-seed parameter
search. Report stability of membership/graph and small populations, not just the
number of clusters or a single ARI. The controller lists these as outstanding;
it does not fabricate completed biological/seed review. Only after these checks
and explicit annotation approval can a result become formal.

A terminal or `review_required` round cannot be continued in place; resolve the
question and start an explicit new session. Retain all previous rounds.

An automatic accept/stop is a controller outcome, not annotation approval or a
claim of global optimality. Compare candidates using a fixed evaluation k and
sampling rule; record common-cell versus full-cohort comparisons when populations
differ. Keep the selected incumbent explicit instead of promoting the latest run.
Network-only review retries belong in supplemental hash-bound records; never
overwrite a frozen failed/degraded round or apply its fallback after escalation.

Full delivery of the selected Scanpy result follows the fixed
[compact A–O layout](rna-overview.md): doublet diagnostics in row three,
composition and three-marker dotplot below. Internal search diagnostics are
not themselves full handoffs; incomplete agent work must remain explicit.
