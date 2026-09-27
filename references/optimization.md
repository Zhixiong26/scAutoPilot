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
Configure an actual adapter command in `config/optimization.yaml` under
`scanpy_mvp.jev.command`; it receives the question/state JSON on stdin and must
return the strict response schema on stdout. With no command, or after an
allowed adapter failure, the output explicitly says
`uncalibrated_rule_fallback_v0`; never describe that run as Jev-driven.

The immutable round is stored under
`.workflow/optimization/<session-id>/round_NNN/` with state, questions,
judgments, decision, and a signed frozen round plan. From round two onward the
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
