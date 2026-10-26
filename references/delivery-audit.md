# Full-analysis delivery self-check

Run this gate at handoff for a full analysis, even if a custom DAG reports all its
tasks complete. Use routes requested by the user, not the routes left in that DAG.
The audit is read-only except for its JSON report; exit 1 means incomplete.

```bash
python tools/audit_delivery.py --project . --run-id PUBLICATION_RUN \
  --routes scanpy --source-run ANALYSIS_RUN --annotation-run ANNOTATION_RUN \
  --require Results/runs/scanpy/ANNOTATION_RUN/scanpy_complete.ipynb \
  --output Results/runs/scanpy/PUBLICATION_RUN/delivery_audit.json
```

For a single standard run, omit `--source-run` and `--annotation-run`. Repeat
`--source-run` for separate scientific producer runs. The optional annotation
binding supports `complete_scanpy_candidate.py`'s derived delivery contract.
Repeat `--require` for every additional promised file (complete notebook, marker
tables, dotplots, reports, etc.); the checker cannot infer promises from chat.

The gate verifies signed task evidence and recorded outputs for all named runs,
formal `figures_comparison` and dependent `workflow_summary`, requested route
coverage, manifest hashes, atlas PNG/PDF/preview and individual panels, fresh
visual review of all previews and at least one single panel, Scanpy cell-type
panels and an executed notebook without recorded errors, optional annotation
source/cell-count/H5AD binding, the results index and extra required artifacts.
Inspect the actual images before recording review; never mark review passed to
silence the gate. A placeholder-free candidate label is not biological approval.

Custom DAG authors must include the comparison and summary tasks or explicitly
name a separate valid publication run at final audit. `overview_preview.png`
alone never substitutes. Disabled figure settings do not waive a promised full
delivery. Explicitly narrower tasks (evidence extraction, environment setup,
appearance edits) are not full-analysis handoffs: validate their declared scope
and do not call the whole analysis complete. Pure appearance changes may still
overwrite directly; refresh affected hashes/review and rerun the gate if handing
off the complete bundle. No unnecessary numerical recomputation is required.
