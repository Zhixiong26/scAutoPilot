# Publication rendering and heatmap audit

Use for all project plotting: final figures, exploratory candidates, temporary
scripts/notebooks, parameter comparisons, marker/composition panels and DMR
heatmap diagnostics. Explicit skill invocation is not required. Follow
[result layout](result-layout.md) for both managed and standalone outputs. The automated seven-route atlas remains governed by
[figures-comparison.md](figures-comparison.md); extra publication panels are
separate derived deliveries and do not retroactively complete that DAG task.

## Freeze the source before rendering

Resolve the exact run, annotation revision, H5AD/coordinate table, metadata,
marker settings and palette. Verify source task evidence and artifact hashes.
Pure appearance adjustments may directly overwrite the requested existing
figures. Do not require a new revision directory, backup copy or user approval
for typography, legend grouping/order, line wrapping, spacing, colours,
display-only point size/opacity, or another presentation-only change explicitly
requested by the user. Preserve cell membership, expression/measurement values,
coordinates, cluster membership and biological label meaning. Do not rewrite
the source H5AD merely to change a figure's appearance.

Render to temporary files and verify them before replacing the requested files;
keep PNG/PDF and affected previews consistent. Update the affected figure
manifest, checksums/sealed artifact records, visual-review record and result
index so an intentional replacement is not reported as artifact corruption.
Do not change historical scientific signatures or invent a new analysis run.
An active writer is a concurrency constraint: wait for it to finish before
replacing its output. A renderer's existing nonempty-directory guard is an
implementation limitation, not a requirement to ask the user or create a
permanent revision; adapt the targeted rendering/publishing step as needed.

Use a new result revision when the change alters data, cell membership,
coordinates, clustering, biological annotation meaning or analysis settings,
or when the user explicitly asks to preserve multiple versions.
Rendering does not rerun PCA, Harmony, neighbors, UMAP, Leiden or training.

The plot-settings record contains source run and analysis signature, annotation
revision/status, label level, category order, explicit palette, marker groups,
expression cutoff/scaling, sample/condition order and point style. Record actual
missing markers rather than silently omitting entire cell types. Derive all names
and sample counts from the current inputs. Never copy IPF labels or thresholds.

Verify exact cell IDs and label correspondence between tables and H5AD; align by
IDs before accessing arrays. Keep coordinate/graph and source-file hashes before
and after rendering. The delivery manifest records all source/settings hashes,
coordinate basis, cells, labels, dimensions, artifacts and visual-review status.
AnnData presentation metadata should use parallel `*_display_order` and
`*_display_palette` arrays, not label-keyed nested dictionaries: labels such as
`T/NK` must not become HDF5 path components.

## Panel requirements

- **Embeddings:** use `embedding_plot.save_embedding()` for 8 × 8 inch,
  300 dpi individual PNGs and matching physical-size PDFs. Axes must be square
  with isotropic data units, preserving the point cloud's natural shape. Check
  both axes geometry and equal horizontal/vertical unit scale; a square canvas
  alone is insufficient. Keep categorical legends single-column and numerical
  bars outside each panel. Atlas canvases may be rectangular with square panels.
- **Colours:** when the user requests a presentation change, apply the requested
  display order/palette and record it consistently across the affected views;
  otherwise preserve the source's explicit display order/palette first, then
  its saved categorical colours; reconstruct only when no explicit source exists
  and record the reconstruction rule. Missing, duplicate or inconsistent entries
  fail rather than silently recolouring. Shared biological labels can share a
  frozen palette; equal Leiden numbers across models do not share identity.
- **Core Scanpy delivery:** where data exist, provide cell type, Leiden, sample,
  verified condition, annotation confidence, before/after Harmony and QC views,
  plus marker and composition tables. Name missing metadata and omitted panels.
  A revised label must propagate consistently through UMAP, dotplot, legend,
  composition table and exported cell annotation.
- **Marker dotplots:** use the recorded expression layer (normally full-gene
  log-normalized `raw`). State whether colour is mean expression or gene-wise
  scaled mean; state the expression cutoff for the fraction/size legend. Align
  row order and marker groups to the selected annotation revision. Export the
  mean/fraction table. Do not force dotplots square or use clipped marker labels.
- **Composition:** export counts and fractions by sample/condition, recording
  denominators and sample counts. Fractions normalized within different
  conditions are separate series, not additive stacked portions of one total.
  Pooled-cell summaries are descriptive, not donor-level differential-abundance
  evidence.
- **Vector output:** describe rasterized scatter layers and embedded heatmap
  rasters honestly. Wrapping a PNG in PDF does not recover vector source data.

Build previews for review without changing the publication originals. Inspect
all previews and heatmaps plus representative single panels for overlap,
clipping, label readability, palette consistency, panel letters and numerical
colour bars. For automatic atlas delivery use `record_figure_review.py`; for
additional publication deliveries save a separate review bound to their hashes.
Successful rendering/hash checks alone mean `rendered_verified`, not visual or
biological approval.

## DMR heatmaps: inspect the matrix before changing the display

Required four-view delivery for every per-sample or pooled methylation DMR
heatmap: `mean_ratio.png`, `zscore.png`, `zscore_colorbar_compressed.png`, and
`zscore_mean.png`. The fourth averages saved single-cell DMR-wise Z-scores within
each cell type (cell-weighted, not donor-balanced); do not Z-score the means.
Require at least 3 finite cells per type/DMR, otherwise retain NA (gray).
Keep the same DMR set/order and export mean values and observed-cell counts.
Default ranges are raw [0,1], Z-score [-3,3], compressed and mean [-1,1]; display
limits never clip the exported values. Comparison deliveries collect all four.
This contract does not apply to expression heatmaps, count-summary charts or
recursive aggregation of an already aggregated diagnostic heatmap.

When heatmaps look blank, inverted, patchy or dominated by one type, first audit
the saved matrices and DMR selection. Record shape, cell/region IDs, per-type
counts, finite-value/coverage fraction, genomic coordinates, DMR direction,
comparison identity, selection threshold and whether p-values were adjusted or
the documented raw-p fallback was used. Confirm which axis holds cells/regions
and how type-block boundaries map to indices.

Keep missing coverage as NaN/masked values; it is not zero methylation. Report
the coverage/support of group means, and mask insufficiently supported means
using a declared minimum. Do not replace missing observations with invented
values to create a clearer diagonal.

Keep raw mean ratio, DMR-wise z-score, and display-compressed z-score distinct.
Record the normalization axis, centering/scaling statistics, clipping and
NaN/zero-variance handling. For a derived group view, mean of per-cell z-scores
is not the same calculation as z-scoring the group means; name the one used.
Do not claim missing raw/FDR significance or perfectly type-specific methylation
from a visually strong heatmap.

Balanced views are optional presentation summaries. If used, freeze explicit
type order, stably order cell IDs within each type, split into disjoint bins and
record the aggregation rule, bin membership and cells per bin. Verify every
source cell appears exactly once; show that visual row size no longer represents
cell abundance. Keep the original full-cell view and matrices. No score-based
cell selection, silent subsampling or changed DMR set is a rendering correction.

Atlas collection only copies/hashes existing heatmaps. Any new aggregation,
matrix audit or balanced view is a separate derived artifact with its own
inputs and manifest. Top-N selection for display remains distinct from the
all-unique pooled-DMR feature set used by MethylVI.

## Source experience

The rules above were reconciled against IPF_final's Scanpy annotation/publication
revisions, `render_publication_0802_revision05.py`, MethylVI weight/threshold
atlases, `render_readable_heatmap_audit.py` and
`render_balanced_dmr_display.py`. These are provenance examples, not runtime
dependencies. Their project paths, palettes, run IDs, selected counts and manual
decisions are intentionally not packaged as universal defaults.

## Custom saved-H5AD embedding revisions

Use `tools/render_embedding_revision.py --project PROJECT --spec SPEC.json
--output NEW_REVISION_DIRECTORY --task-dir TASK_DIRECTORY` as a custom DAG task.
The JSON specification contains `source` (`path`, `sha256`, `run_dir`, `task_id`),
`annotation_status`, `description`, optional `point_size`, and a `panels` list
(`key`, `title`, `kind`: categorical or continuous). All source columns must exist.
The declared source task must have valid evidence and list that exact H5AD.

The renderer exports numbered individual PNG/PDF panels, low-resolution previews,
a preview-only contact sheet, coordinates/labels and composition tables, and a
checksum-bound manifest. It checks 2400×2400 pixels, square axes with isotropic
units, external single-column categorical legends, and vertical numerical bars.
Source palettes take precedence; a Scanpy default reconstruction is named as such.
No clinical condition or new annotation is inferred. Review every preview and
representative full-size categorical/numerical panels, then save a separate
hash-bound review. Do not call a general preview readability pass a geometry pass.

## Shared RNA–DNAm marker panels

For cross-modality marker dotplots read [shared marker selection](methylome-markers.md).
Keep discovery criteria, uniqueness, representative nomination and plotted-gene
counts separate. Export gene–type support and both normalization formulas;
a negative colour scale does not identify a method. Main shared-candidate panels
and strict uniqueness supplements can coexist without changing the original tests.
These panels are distinct from the four-view DMR heatmap contract above.
