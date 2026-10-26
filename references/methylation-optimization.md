# MethSCAn and MethylVI iteration / 甲基化迭代闭环

Use this reference for methylation improvement, not Scanpy's RNA grid.

For published method choices read [literature-backed methods](published-methods.md).
It covers MethSCAn feature semantics, ALLCools controls, chooseR/scIB applicability,
the optional executable Optuna capacity-proposal bridge, and DMR sensitivity.
The bridge is an outer-loop advisor, not automatic retraining or a new inner-loop
selection objective; existing grids and acceptance gates below remain unchanged.

- **Executable inner loop (0.13):** `methylation_iteration` DAG tasks screen a
  verified retained representation, preserve the incumbent, avoid repeated or
  infeasible settings, and check graph/partition stability across seeds.
- **Agent-managed outer loop:** diagnose feature/model defects, predeclare a
  bounded experiment, execute a separate DAG, and compare evidence. It is not
  an unattended discovery/retraining daemon. Do not promise background continuation
  unless an actual controller was submitted.

## Establish the experiment

Record source run/task, input/annotation revisions, genome/context, cell IDs,
region coordinates/order, matrix semantics and model settings. Bind the H5AD to
completed task artifacts. Name the defect: fragmentation, weak local support,
donor/depth association, missing coverage or unstable groups. DMR count/significance,
supervised separation and a predetermined RNA cluster count are not objectives.

Keep one incumbent per comparable cell/feature/model experiment. Baseline,
candidate, rejected, selected and formally reviewed are distinct states. Inspect
ordinary UMAP, cluster sizes, sample/condition composition, coverage overlays and
biological evidence. Sample segregation may be biological: do not maximize global
donor mixing or erase genuine PF/Donor differences.

## MethSCAn: representation first, then justified feature experiments

1. Audit cell/region missingness, observed VMR counts, imputation settings,
   depth/methylation distributions and per-sample retention. Missing coverage is
   not zero methylation. Freeze QC/cell selection for the inner loop.
2. Start from completed `methscan_vmr.h5ad` with `X_pca`, graph, Leiden and UMAP.
   Screen resolution, neighbors and PCs consumed by the graph before min_dist.
   Retained-PC truncation is **not** re-estimating PCA or imputation:
   `04_vmr_scanpy.py` also uses its PC setting during iterative imputation,
   which the inner loop deliberately freezes.
3. Only if retained capacity or feature/coverage evidence identifies an upstream
   defect, plan a separate VMR/matrix experiment. Change one family at a time:
   variance threshold, smoothing/scan scale, region/cell missingness, or
   imputation/PCA construction. Declare the reason, candidate set and budget.
4. Compare retained cells/regions and sample composition first. If cell sets
   differ, report full-cohort retention and common-cell comparisons. Do not remove
   poorly covered cells silently to improve scores. Compare stability, coverage
   sensitivity and biological support, not VMR count or round islands. Preserve
   alternatives when incomparable evidence cannot rank feature sets.
5. Apply the inner loop to shortlisted representations, then choose using outer
   evidence. Review rare populations and labels against each new partition.

### Dependency and reuse boundary

| Change | Earliest affected work | Verified inputs that may remain |
|---|---|---|
| Colours/legend | Rendering | Coordinates, graph, matrix, model |
| min_dist | UMAP | Leiden and graph |
| Resolution | Leiden | UMAP, graph, representation |
| Neighbors / retained PCs | Graph, Leiden, UMAP | Saved representation, upstream matrix |
| Imputation / PCA construction | Representation and downstream | Compatible region definition and raw matrix |
| VMR threshold / scan settings | VMR scan, matrix and downstream | Compatible converted/prepared/filtered/smoothed inputs |
| Smoothing bandwidth | Smooth and dependent branches | Compatible conversion/prepare/filter |
| Cell inclusion / context / genome | Re-evaluate earliest scientific dependency | No blanket reuse promise |

Reuse requires matching relevant inputs, parameters, code and completion evidence.
The global-signature DAG does not automatically substitute cross-run stage caches.
A reuse-aware planned task must name verified artifacts; never edit an old
signature to force reuse. The inner loop does not reconvert ALLC.

## MethylVI: diagnose → cheap screening → selective retraining

1. Audit counts/feature provenance and model completion: integer `mc/cov`, valid
   coverage, exact cell/region identity, explicit batch metadata. Examine training
   trajectories, observed feature support and latent-depth/sample associations.
   Missing training history remains missing evidence.
2. Start from `methylvi_embedding.h5ad`, consuming **all** `X_methylVI` dimensions.
   Latent axes are not ranked PCs. Screen graph/Leiden without training; do not
   truncate latent axes as a substitute for changing `n_latent`.
3. If a model/feature defect remains, plan a bounded outer experiment. Separate
   feature families (VMR, VMR+DMR, ALLCools), feature counts and capacity/training
   changes. `analysis.methylvi.n_latent`, `n_hidden`, `n_layers` now reach the
   shared trainer (defaults still 20/128/1). Epochs, batch size, seed and validation
   fraction retain their config interfaces. A capacity change requires new
   training, not renaming an old checkpoint. New training saves actual split
   cell IDs and histories.
4. Compare validation loss only under compatible feature/count definitions and
   actual held-out membership. Equal fractions do not establish equal splits;
   losses from different feature sets have different scales. Lower loss alone
   cannot rank cell identities. Track convergence, unsupervised structure,
   donor/coverage confounding and biological support separately.
5. Short pilots reject failed configurations; do not rank an undertrained pilot
   against a converged incumbent as if budgets matched. Train shortlisted settings
   adequately. Confirm finalists with independent **training** seeds and equal
   graph-screening budgets; inner-loop graph seeds do not establish training
   stability. Preserve rare-group evidence, not just global mean scores.
6. Deliver ordinary and supervised-weight sensitivity views separately. RNA
   labels and label-derived DMRs are dependent evidence, especially for VMR-only
   vs VMR+DMR. Do not count their agreement twice as independent validation.

The model/latent distinction follows the [MethylVI documentation](https://docs.scvi-tools.org/en/1.3.3/user_guide/models/methylvi.html).
The staged search and thresholds are scAutoPilot engineering policy, not a claim
that the model authors validated this search procedure.

## Execute the inner loop

Add an explicit `analysis.methylation_iteration` list to a new/idle runtime's
`config/analysis.yaml`. It is **not** enabled by `--routes auto`. Example values
must match the actual source; never infer sample/label columns or source paths.

```yaml
analysis:
  methylation_iteration:
    - id: vmr_graph_review
      mode: methscan                 # or methylvi
      source_run: SOURCE_RUN
      source_task: SOURCE_TASK
      source_h5ad: Results/runs/SOURCE_RUN/path/to/embedding.h5ad
      sample_key: sample_id
      label_key: cell_type           # optional diagnostic, not ground truth
      qc_keys: [n_observed_vmrs]     # actual columns; [] records missing QC
      baseline: {n_pcs: 30, n_neighbors: 15, resolution: 0.8, min_dist: 0.5}
      grids:
        n_pcs: [20, 30]
        n_neighbors: [10, 15, 30]
        resolution: [0.4, 0.8, 1.2]
        min_dist: [0.3, 0.5, 0.7]
      max_rounds: 12                 # includes baseline, not convergence proof
      patience: 5
      max_seconds: 14400             # between-stage checks, not hard timeout
      evaluation_cells: 3000         # fixed cell-ID hash sample, maximum 5000
      evaluation_k: 15
      seed: 0
      confirmation_seeds: [11, 23]
      min_seed_ari: 0.8
      min_cluster_jaccard: 0.5
      stability_tolerance: 0.05
```

MethylVI requires `mode: methylvi`, full latent dimension as baseline `n_pcs`,
and a singleton grid (e.g. `[20]`). This shared graph schema field does not make
latent axes PCs. The loader rejects dimension, neighbor/resolution or metadata
mismatches, and min_dist inconsistent with saved UMAP a/b at spread 1.

```bash
python tools/plan_workflow.py --project PROJECT --routes methylation_iteration --run-id NEW_RUN
python tools/submit_workflow.py --project PROJECT --run-id NEW_RUN
python tools/inspect_run.py --project PROJECT --run-id NEW_RUN
```

Independent listed experiments have no artificial serial dependencies. They use
the `plot` profile and `scanpy_allcools` environment, not the trainer profile.
Inspect resources before submission; size memory for retained graphs and bounded
metrics. This artifact-only route does not reread full ALLCs. Source completion
and new runtime/config validation remain mandatory.

## Selection, stopping and delivery

Adjacent single-axis moves use the **best**, not latest, candidate. Reject material
regressions against both incumbent and initial baseline. Screen silhouette/DB in
a frozen source representation, tiny-cluster fraction and fixed-k UMAP preservation.
This favors baseline-compatible structure and is a heuristic, not independent
biological validation. Layout improvements remain layout-only. Labels, DMR counts
and supervised separation do not drive selection. Missing baseline metrics stop
for review. Sample/coverage diagnostics require separate scientific assessment.

Stop at round/time/patience budgets, exhausted local candidates, invalid provenance
or a change outside scope. Budget exhaustion is not convergence/global optimality.
Confirm baseline and the screened winner with fresh graph/Leiden seeds, global
ARI and **per-cluster** best Jaccard. An unstable winner, skipped confirmation or
incomplete baseline retains the source and requires review. Stability thresholds
are configurable screening rules, not p-values.

`Results/runs/<category>/<run>/methylation_iteration/<id>/` contains source evidence/spec,
per-round metrics/coordinates, candidate comparison, seed confirmation, diagnostics,
cluster-by-sample/label tables, a representation-only selected H5AD (not full
counts), selection summary, figure comparison and checksum manifest. Computational
completion is not annotation/biological/visual approval. Standard DAG completion
indexes verified outputs in `Results/RESULTS_INDEX.md`.

Partial/failed directories are preserved; in-place resume/overwrite is refused.
Use a new run after diagnosis. Do not mutate source results, running frozen jobs
or approved RNA/DMR annotations.

## DMR: inference/sensitivity, not an aesthetic objective

Freeze contrast, grouping, direction, genome/context, coverage rules and statistical
unit. Pooled cell-type DMRs are not donor-level PF-vs-Donor inference. Disease
inference uses donor replicates, not cells as independent donors; see
[dmrseq replication requirements](https://bioconductor.org/packages/devel/bioc/vignettes/dmrseq/inst/doc/dmrseq.html).
Assess coverage eligibility, effect direction/size, donor support and regional
stability under predeclared sensitivity changes. Do not automatically relax
p/FDR or effect thresholds to increase DMR counts or enhance heatmaps. Raw-p
fallback is not FDR significance. Four heatmap views and Top-N display remain
separate from all-unique-DMR model features. Layout-only changes do not rerun DMR.
