# Categorized results and project-wide figure rules

This contract applies to production, parameter searches, diagnostics, recovery,
annotation revisions and exploratory scripts, including work outside a skill DAG.
New output roots are `Results/runs/<category>/<run-id>/`. Purpose words such as
`exploration`, `recovery` or `revision` belong in the run ID or inside the run;
they do not replace its method category.

## Category ownership

| Category | Ownership |
|---|---|
| `scanpy` | RNA analyses, doublet comparisons, PCA/Harmony/UMAP searches and RNA annotation/figure revisions |
| `methscan` | Native MethSCAn VMR/DMR, its clustering and retained-PC exploration |
| `vmrseq` | Native vmrseq VMR discovery and its diagnostics |
| `allcools` | ALLCools bin/features and its native representation exploration |
| `methylvi` | MethylVI models, batch correction, latent/neighbor/weight searches, whether features came from MethSCAn, vmrseq or ALLCools |
| `multiomics` | Joint RNA–DNAm atlases, shared markers, disease/coupling analyses and deliveries spanning methods |
| `benchmark` | Explicit reference/accelerated or cross-method benchmark experiments |
| `methylation_qc` | Methylation-only read-depth/conversion/coverage QC independent of a modeling method |

Built-in planners derive ownership from the selected final analysis. Prerequisite
conversion/feature-building tasks remain inside that run; they are not duplicated
in another category. An independent producer and consumer retain separate run
roots and explicit source links. Mixed analysis DAGs use `multiomics`; the
custom planner requires `--category`, because a task/run name is not sufficient
evidence of its purpose. New categories need an explicit registry update, not an
ad hoc spelling (`methylvi` is canonical).

## Single source of paths

- `tools/result_paths.py` resolves the owning `Results` link and validates IDs,
  categories and collisions. New plans freeze `result_layout_version: 2`,
  `result_category` and absolute `result_dir`; execution and submission check them.
- Custom commands use `{result_dir}` for output paths. Do not rebuild a path from
  `{project}/Results/runs/{run_id}` or depend on the caller's working directory.
  Output flags with the common hardcoded form are rejected before planning.
  This check is not a filesystem sandbox: inspect arbitrary adapter scripts too.
- `.workflow/runs/<run-id>/` stays the scheduler/evidence directory. Run IDs are
  unique across categories in an owning project. Reports and consumers use the
  recorded `result_dir`, never assume the category from a prefix.
- For standalone exploration, reserve a new root with:

  ```bash
  python tools/reserve_results.py --project PROJECT --category methylvi \
    --run-id methylvi-neighbor-search-YYYYMMDD-01 --source-run SOURCE_RUN
  ```

  Pass the printed absolute path to the exploration script. The adjacent
  `result_manifest.json` records a reservation, not task completion. DAG work uses
  `plan_workflow.py` or `plan_custom_workflow.py --category ...` directly instead
  of reserving the same ID first. A retry reads its original manifest/plan.

Pure appearance edits may replace existing figures in place; they do not require
a new run or publication revision. Preserve scientific data and update affected
manifests, checksums, visual review and index links. See
[publication figures](publication-figures.md) for this replacement policy.

Within a run, group artifacts by function (`tables/`, `models/`, `reports/`,
`publication/<revision>/`) or parameter branches. Existing native stage layouts
can remain. Do not create empty subdirectories just to satisfy a template. A
render-only revision may live within the source run's new publication revision;
a separately scheduled render gets a new run under the same owning category.

For one newly planned annotation revision, schedule related annotation, heatmap,
overview, dotplot and publication-comparison tasks in the same DAG/root, with
subdirectories for requested label systems and artifact roles. A separate render
run, when necessary, is a linked supplement to the canonical annotation entry,
not another final delivery. Do not duplicate competing methods by default. See
[RNA cluster correlation](rna-reference-correlation.md). User-authorized retirement
of a superseded method requires dependency checks, removal records, updated
indexes and delivery validation; keep upstream files required by the selected
method. Skill synchronization alone never authorizes deleting results.

## Figures everywhere

Read [publication figures](publication-figures.md) before any plotting, including
temporary Python/R/notebook plots and parameter-search candidates. Generated
projects carry an `AGENTS.md` with the core contract, so explicit skill invocation
is not needed. Project-specific instructions can link the full local skill.

An exploratory label changes evidence status, not rendering standards. Individual
embedding PNGs use the shared `save_embedding()` (8×8 inches, 300 dpi, 2400×2400,
square equal-aspect axes, external one-column legend or vertical colorbar, no
tight crop). Preserve category order, palettes, coordinates and exact cell IDs.
Dotplots, heatmaps, benchmark charts and comparison canvases use layouts suited
to their data; the square rule applies to individual embeddings. DMR heatmaps
retain the four-view contract when applicable.

Every delivered figure revision has source/settings and table data, a manifest
with hashes/geometry, and a separately recorded visual review. Deliver one final PNG per figure; do not create PDF or duplicate preview/review
images or preview-only contact sheets. Diagnose a failure rather than declaring an unchecked figure
compliant. Automated geometry checks do not replace inspection of clipping,
labels, legends and biological meaning. The user may authorize first-pass final
figures without a permission round; visual inspection still occurs.

## Existing results and upgrades

This release changes runtime code/signatures. Distribute a new runtime and
revalidate before creating a new plan; leave active/frozen executors intact.
Legacy plans without layout version 2 continue to read their exact recorded
paths. Skill synchronization never silently relocates historical data.

Moving old runs is a separate migration: inventory producers/consumers and
active jobs, record old→new paths, preserve evidence, then validate links and
index entries. Do not use new flat symlink aliases as the normal output scheme.
Index verified artifacts by their real paths using the existing completion hook;
preserve human notes and historical entries. A reserved output is not a result.
