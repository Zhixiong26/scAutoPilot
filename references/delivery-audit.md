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
For full RNA handoff also pass `--overview-manifest` for the integrated A–O
main figure, or register it in project `config/figure_delivery.json` under
`rna_overview_manifests`. The checker then automatically applies the
[RNA overview contract](rna-overview.md), including three markers per annotation,
source-table arithmetic, PNG inventory and a fresh main-figure visual review.
`--require` alone checks file existence/hash, not this content contract. Historical
deliveries remain readable with their frozen checker; the current full-scope
Scanpy audit requires the new contract.

The gate verifies signed task evidence and recorded outputs for all named runs,
formal `figures_comparison` and dependent `workflow_summary`, requested route
coverage, manifest hashes, final atlas PNGs and individual panels, fresh
visual review of all final atlas PNGs and at least one single panel, Scanpy cell-type
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

## Mandatory complete RNA figure gate (0.16.7)

`audit_delivery.py --routes scanpy` requires a registered `rna_full_v1` overview,
even if figure_delivery.json is absent. Follow [the RNA manifest contract](rna-overview.md).
The main PNG includes doublet diagnostics, annotation/QC, composition and marker
dotplot. Missing overview registration, missing doublet source tables, inconsistent
singlet IDs or stale visual review fail delivery. Explicit scientifically
not-applicable doublet handling needs a reason and hash-bound decision source.

New Scanpy plans freeze this contract; summary execution runs the audit and the
inspector reports `awaiting_complete_delivery` while numerical tasks remain
complete. Agent work continues through marker interpretation, rendering and
visual review. Existing plans are not silently rewritten. A scoped figure
proposal can be checked with `audit_rna_overview.py --require-full`; this does
not claim that a new numerical DAG ran or grant biological approval.
