# ALLCools and MethylVI

Before new paired-model fitting, follow [paired doublets](paired-doublets.md).
MethylScrublet scores DNAm mc/cov, not MethylVI latent or supervised UMAP;
training consumes the finalized cell-level mask shared with RNA. A prior RNA
Scrublet filter is not evidence of this paired policy having been executed.

ALLCools may rank blacklist-filtered bins for feature selection. MethylVI must use integer per-cell/per-feature `mc` and `cov`, not hypo-score.

Require unique cells/features, integral nonnegative counts, `mc <= cov`, explicit batch metadata, and a source manifest. Derive expected cells from the filtered-cell authority; zero is never a runtime default. Context, references, thresholds, feature targets, epochs, batch size, and the validation fraction come from `analysis.yaml`. Nested feature targets come deterministically from one ranked maximum-feature input. `methylvi.validation_fraction` reaches scvi as `validation_size`, and `train_size` is set to `1 - validation_fraction` alongside it: scvi defaults `train_size` to 0.9 on its own and rejects `train_size + validation_size > 1`, so passing only the validation size would fail for any fraction above 0.1.

VMRs and ALLC manifests must share a completed MethSCAn signature. VMR+DMR retains selected VMRs and appends only merged pooled DMRs with zero genomic overlap.

New ALLCools count checkpoints bind the ALLC table hash and selected source-file
metadata (resolved path, size, mtime/ctime), as well as cells, coordinates, metadata,
bin size and context. The output H5MU embeds that manifest's digest. Legacy or
source-mismatched caches are refused; use a new work/output directory, never stamp
new provenance onto unverified old counts. Source metadata checks do not reread
entire ALLC files and are not a raw-data content-checksum claim.

Export latent embedding, ordinary UMAP/Leiden, supervised sensitivity views, methylation QC, summaries, and completion markers under the run-specific result root. Ordinary UMAP remains the primary latent-structure view.

ALLCools reuses the common MethSCAn selection/prepare/filter chain because its expected-cell authority and COV inputs come from the filtered manifest. It does not require smooth or VMR scan unless a VMR route is also selected.

Three routes share one training core: `allcools` (5-kb bins), `vmr` (variance-thresholded VMR regions), and `vmr_dmr` (selected VMRs plus every unique pooled DMR). Each route owns a `00_*_config.sh` declaring its directory layout and defaults; `vmr_dmr` reuses the `vmr` feature inputs rather than rescanning ALLCs, so it depends on that route's completed signature. Route configs resolve the shared experiment values from the entry `00_experiment_config.sh` and re-export them under the neutral `SCMO_*` names, so a stage reads one namespace regardless of which route invoked it. `SCMO_MVI_EXPERIMENT_ROOT` is the parent of all routes; `SCMO_MVI_ROOT` is only its `allcools/` subdirectory.

The packaged `run.sh` runners and `slurm/*.sbatch` wrappers execute one stage without a plan, for exploration, smoke testing, and recovery. They resolve resources from scheduler profiles, verify the same completion markers the DAG does, and never substitute for a run's completion evidence. Production MethylVI work goes through the run DAG.

## Batch comparison

Native ALLCools UMAP/L1 and MethylVI UMAP/methylVI_leiden are distinct deliveries. MethylVI ordinary and supervised views use separate atlases. A valid supervised skip retains ordinary figures and records a reason; missing expected coordinates fail. See [batch delivery](figures-comparison.md).

## Diagnose and iterate

For retained-model comparisons, read [MethylVI unsupervised iteration](iteration-practice.md#methylvi-unsupervised-iteration).
Audit coverage, depth, sample effects and seed stability before changing the
model. Resolution-only candidates preserve the latent representation and graph;
neighbors-only candidates preserve the latent representation. Label purity can
increase merely through splitting; RNA references and supervised UMAP separation
are not independent validation. Extra model searches require their own planned
tasks. The executable `methylation_iteration` route screens retained latents without
retraining; see [the complete inner/outer loop](methylation-optimization.md).
For optional official Optuna capacity proposals and external method readiness,
read [literature-backed methods](published-methods.md). Optuna proposes; signed
DAG tasks train; comparable validation losses screen; stability/biological review
selects. scvi autotune/ASHA and donor-held-out training are not implicitly enabled.
