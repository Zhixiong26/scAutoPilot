# Automatic Scanpy review MVP

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
step; it never invents a continuous value or changes two logical axes.

## Evidence and judgments

`tools/review_scanpy_iteration.py` computes:

- UMAP reviewer: trustworthiness and KNN preservation.
- Clustering reviewer: silhouette and Davies–Bouldin; when available, cell-type
  ASW, normalized iLISI, and batch ASW.

An automatic candidate annotation derived from the same Leiden partition is
marked circular. Its cell-type ASW is recorded for audit but cannot serve as
independent biological validation. Only an approved independent annotation can.

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
files. `system_one_commercial` uses the same adapter with OpenAI, Anthropic, or
Gemini. `typesafe_jev` is a separately named future backend; local adapter
results must never be labelled as Jev. When the configured backend is absent or
fails and fallback is allowed, the result explicitly says
`uncalibrated_rule_fallback_v0`.

The immutable round is stored under
`.workflow/optimization/<session-id>/round_NNN/` with state, questions,
judgments, `backend_audit.json`, decision, and a signed frozen round plan. From round two onward the
state includes the previous parameter change and per-metric deltas. A new run
whose parameters do not match the preceding frozen plan is refused.

## One iteration

After a candidate run is complete and `inspect_run.py` has produced valid
evidence, use the project's Scanpy/analysis environment (it must provide
AnnData, NumPy, and scikit-learn):

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

Hard stops are independent of the model: 20 rounds, five consecutive rounds
without objective improvement, the configured accept threshold, an escalation,
an exhausted grid boundary, or an explicit no-change decision. Submission still
obeys the normal authorization and scheduler rules.
