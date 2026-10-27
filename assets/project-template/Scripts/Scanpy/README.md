# Scanpy notebook workflow contract / Scanpy Notebook 操作契约

This file describes the long-lived objectives, boundaries and verification rules for whoever executes this analysis — a person or an automated skill. Run status, failure evidence and correction records belong in `Report.md`; do not maintain volatile parameters in two places.

本文件面向执行该分析的人或自动化 skill，描述长期稳定的目标、边界和验证规则。运行状态、失败证据和修正记录写入 `Report.md`，不要在两处重复维护易变化的参数。


## Current full-delivery requirement / 当前完整交付要求

The notebook below describes the legacy numerical backend, including Scrublet;
it does not override a user-selected scDblFinder adapter. Read the project skill
`references/scanpy.md` and `references/rna-overview.md` for the complete workflow.
Every automated full RNA handoff includes one compact A–O PNG: A–D annotation,
E–H confidence/QC, I–L doublet diagnostics in row three, M–N composition, O marker
dotplot with three supported genes/type. Use `tools/rna_overview_layout.py`;
single-line grouped legends, PNG only, no duplicate preview/PDF. Save actual
geometry, sources and visual review. Numerical notebook success alone does not
complete delivery; new `rna_full_v2` plans enforce the full audit.

默认完整交付为五排总图，doublet 四图固定第三排；缺图、缺 marker、坐标/细胞
不一致或过期审图记录均不算完成。无需重跑已完成数值分析来修补排版。

## Scope / 适用范围

Bundled numerical entry point / 内置数值分析入口：

- `Notebooks/<notebook>.ipynb`（打包入口 / packaged entry: `Notebooks/scanpy_workflow.ipynb`）

The notebook reads the 10x filtered matrices of the samples declared by the sample manifest and performs QC, Scrublet, normalization, HVG, PCA, Harmony, neighbour graph, UMAP, Leiden, markers, agent-proposed annotation with human review and result export. `CYL` / `ZCP` are example sample labels (示例/example) that illustrate the manifest; they are not defaults.

该 Notebook 负责读取样本清单声明的 RNA 10x filtered matrices（示例样本名 / example sample labels: `CYL`、`ZCP`），完成 QC、Scrublet、归一化、HVG、PCA、Harmony、邻接图、UMAP、Leiden、marker、自动候选注释与人工复核和结果导出。

Validated project adapters may implement selected scDblFinder, external cluster-correlation annotation and complete figure delivery through the signed custom DAG. Scheduler wrappers alone do not prove completion. Never transplant another run’s numeric cluster mappings. 经验证的项目适配器可实现已选 scDblFinder、群相关注释及完整交付；使用同一签名 DAG 与证据规则。

Run root / 运行根目录：`Results/runs/scanpy/<run-id>/`。Below, `Results/runs/scanpy/<run-id>/scanpy/` denotes the Scanpy output directory of that run（下文 `Results/runs/scanpy/<run-id>/scanpy/` 表示该运行下的 Scanpy 输出目录）。

## Invariants and permission boundaries / 不变量与权限边界

- Inputs are the RNA matrices declared by the sample manifest (`rna_path` / `rna_format`; source example: project `Data/Matrix/`), read-only during the analysis.
  输入为样本清单声明的 RNA 矩阵（`rna_path` / `rna_format`；来源示例 / source example: 项目 `Data/Matrix/`），分析期间只读。
- Formal outputs live in `Results/runs/scanpy/<run-id>/scanpy/`, where `<run-id>` identifies this run. 正式输出位于 `Results/runs/scanpy/<run-id>/scanpy/`，`<run-id>` 为本轮运行的标识。
- The original integer expression is preserved in `layers['counts']` of the downstream HVG work object; the full-gene log-normalized expression is preserved in `raw`. If whole-gene raw counts are needed later, the save interface must be extended separately.
  原始整数表达在下游 HVG 工作对象中保留于 `layers['counts']`；全基因 log-normalized 表达保留于 `raw`。若未来需要全基因原始 counts，必须另行扩展保存接口。
- Cluster numbers from other samples or historical runs are not mapped directly onto the current cells. 不把其他样本或历史运行的 cluster 编号直接映射到当前细胞。
- When the user requests iterative execution, continue within that requested scope using configured parameters and new candidate runs. The automatic MVP searches only PCs, neighbors, resolution and min_dist; other scientific changes are separate experiments. This template does not grant execution authorization on its own.
  用户要求执行迭代时，在已授权范围内通过配置和新候选运行持续推进。自动 MVP 仅搜索 PCs、neighbors、resolution 和 min_dist；其他科学参数变化作为独立实验记录。模板本身不代表执行授权。
- A complete candidate may be delivered FOR REVIEW before biological approval. Preserve scientific outputs; layout approval alone never approves cell identities.
  完整候选图先交付并标明待审批；保留科学数据，排版批准不等于注释批准。
- "Pass" is never manufactured by relaxing validation, deleting failure evidence, or chasing historical numbers.
  不通过放宽验证、删除失败证据或追求历史数字来制造“通过”。

## File roles / 文件角色

- `README.md`：the stable operational contract, updated only when workflow objectives or constraints change.
  稳定操作契约，仅在工作流目标或约束改变时更新。
- `Report.md`：current status, baseline, per-round verification and correction decisions; updated after every round.
  当前状态、基线、每轮验证和修正决策；每轮工作后更新。
- Notebook（`Notebooks/<notebook>.ipynb`；打包入口 / packaged entry `Notebooks/scanpy_workflow.ipynb`）：the single source of truth for the analysis implementation and parameters.
  分析实现和参数的唯一事实来源。
- `Results/runs/scanpy/<run-id>/scanpy/scanpy_workflow_executed.ipynb`：the complete executed copy of the most recent verified run; the canonical notebook stays output-free and error-free when committed.
  最近一次通过验证的完整执行副本；canonical Notebook 提交时保持零输出、零错误。
- `confirmed_parameters.json`：the machine-readable parameters a formal run actually adopted. 一次正式运行实际采用的机器可读参数。
- `figure_manifest.json`：the list of figures a run actually exported. 一次运行实际导出的图片清单。

## Notebook analysis workflow / Jupyter Notebook 具体分析流程

The workflow below corresponds to the current implementation of the packaged notebook `Notebooks/scanpy_workflow.ipynb`. The run mode and the iterable parameters are concentrated in the parameter cell; in the template that cell reads them from the JSON sidecar named by `$SCMO_SCANPY_PARAMETERS`. The values in the tables below are template starting points, and an actual run is still governed by the notebook cells and that run's parameter JSON.

以下流程对应当前打包 Notebook `Notebooks/scanpy_workflow.ipynb` 的实现。运行模式及可迭代参数集中在参数单元；模板中该单元从 `$SCMO_SCANPY_PARAMETERS` 指向的 JSON sidecar 读取。表中的参数是模板起点值，实际执行时仍以 Notebook 单元和本轮参数 JSON 为准。

### 1. Initialization and input reading / 初始化与输入读取

- Import Scanpy, AnnData, Scrublet, Harmony, Pandas, NumPy and plotting libraries; fix the random seed at `RANDOM_SEED = 0`.
  导入 Scanpy、AnnData、Scrublet、Harmony、Pandas、NumPy 和绘图库，固定随机种子 `RANDOM_SEED = 0`。
- `RUN_KIND='baseline'` uses the formal output interface and requires `ITERATION_ID=None`; `RUN_KIND='candidate'` requires a unique `ITERATION_ID` and writes to `Results/runs/scanpy/<run-id>/scanpy/iterations/<ITERATION_ID>/`.
  `RUN_KIND='baseline'` 使用正式输出接口且要求 `ITERATION_ID=None`；`RUN_KIND='candidate'` 要求唯一 `ITERATION_ID`，并写入 `Results/runs/scanpy/<run-id>/scanpy/iterations/<ITERATION_ID>/`。
- An existing candidate directory raises an error immediately, preventing directory reuse or overwriting of the previous round's evidence.（模板说明 / template note: the packaged notebook raises unless `overwrite_data_outputs` is explicitly enabled to resume in the same run directory; a new `ITERATION_ID` always stays isolated.）
  已存在的 candidate 目录会直接报错，避免复用目录或覆盖上一轮证据。（模板说明：只有在显式允许 `overwrite_data_outputs` 时才允许在同一 run 目录续跑；新的 `ITERATION_ID` 始终隔离。）
- Read each sample's 10x filtered matrix from the manifest-declared input path (source example: `CYL`, `ZCP` under `Data/Matrix/`).
  从样本清单声明的输入路径分别读取各样本（示例 / example: `CYL`、`ZCP`）的 10x filtered matrix。
- Unzip ZIP inputs in a temporary directory and read the standard `filtered_feature_bc_matrix/` with `sc.read_10x_mtx(..., var_names='gene_symbols', make_unique=True)`.
  在临时目录解压 ZIP，并使用 `sc.read_10x_mtx(..., var_names='gene_symbols', make_unique=True)` 读取标准 `filtered_feature_bc_matrix/`。
- Prefix every barcode with the sample's `cell_id_prefix` (source example: `CYL_`, `ZCP_`), record the origin in `obs['cohort']`, and check the input paths and cell IDs.
  给每个 barcode 添加样本前缀（示例 / example: `CYL_`、`ZCP_`），在 `obs['cohort']` 记录来源，并检查输入路径和 cell ID。
- Carry manifest `sample_id`, `condition` and `batch` into categorical observation columns. The configured group field uses declared condition; absent values remain missing.
  将清单中明确声明的 `sample_id`、`condition`、`batch` 保存为分类元数据；配置的 group 字段使用 condition，缺失值不从样本名推断。
- Copy the unnormalized integer matrix into `layers['counts']`; mark mitochondrial genes (`MT-`) and ribosomal genes (`RPL`/`RPS`) by gene name. Prefixes come from project configuration.
  将未归一化整数矩阵复制到 `layers['counts']`；按基因名标记线粒体基因 `MT-` 和核糖体基因 `RPL/RPS`。前缀来自项目配置。

### 2. Pre-filter QC exploration / 过滤前 QC 探索

- Compute `total_counts`, `n_genes_by_counts`, `pct_counts_mt` and the ribosomal fraction with `sc.pp.calculate_qc_metrics()`.
  使用 `sc.pp.calculate_qc_metrics()` 计算 `total_counts`、`n_genes_by_counts`、`pct_counts_mt` 和核糖体比例等指标。
- Per cohort, plot the 20 highest-expressed genes, QC violin plots, and the `total_counts–pct_counts_mt` and `total_counts–n_genes_by_counts` scatter plots.
  每个 cohort 独立绘制最高表达的 20 个基因、QC 小提琴图、`total_counts–pct_counts_mt` 和 `total_counts–n_genes_by_counts` 散点图。
- Review thresholds against the actual distribution of both cohorts; do not inherit thresholds automatically from another notebook or project.
  根据两个 cohort 的实际分布审核阈值，不从其他 Notebook 或项目自动继承阈值。

### 3. Basic QC and gene filtering / 基础 QC 与基因过滤

Each cohort applies the current candidate thresholds independently / 每个 cohort 独立应用当前候选阈值：

| 参数 / Parameter | 当前值 / Current value | 判定 / Rule |
|---|---:|---|
| `MIN_GENES` | 200 | `n_genes_by_counts >= 200` |
| `MAX_GENES` | 6000 | `n_genes_by_counts < 6000` |
| `MIN_COUNTS` | 500 | `total_counts >= 500` |
| `MAX_MT_PERCENT` | 5.0 | `pct_counts_mt < 5.0` |
| `MIN_CELLS_PER_GENE` | 3 | cohort 内 `filter_genes(min_cells=3)` / within the cohort |

The notebook writes the basic-QC verdict to `obs['pass_basic_qc']` and records the per-cohort cell counts before and after filtering. If any cohort has fewer than 100 cells after basic QC, stop, so that doublet inference is not run on an unstable neighbourhood.（模板中该下限为配置项 `scrublet_min_cells`，来源值 100 / template: the floor is the configured `scrublet_min_cells`, source value 100.）

Notebook 把基础 QC 判定写入 `obs['pass_basic_qc']`，记录各 cohort 过滤前后细胞数。若任一 cohort 在基础 QC 后少于 100 个细胞，则停止，避免不稳定的 doublet 推断。

### 4. Per-cohort Scrublet / 分 cohort Scrublet

- Scrublet uses only the raw `layers['counts']` of cells that passed basic QC, and runs per cohort before the samples are merged.
  Scrublet 只使用通过基础 QC 的原始 `layers['counts']`，在合并样本前分别运行。
- The expected doublet-rate prior is `doublet_rate_per_1000 × current cohort cell count / 1000`; use the run's sidecar for the coefficient. The packaged notebook retains Scrublet's automatic calls. A rate-quantile threshold is a distinct policy, not the same as specifying this prior.
  预期 doublet 率为 `doublet_rate_per_1000 × 当前 cohort 细胞数 / 1000`，系数以本轮参数 sidecar 为准。模板保留 Scrublet 自动判定；按率取分位阈值是另一种策略，不能与预期率参数混为一谈。
- Currently `n_prin_comps=30`, `use_approx_neighbors=False` and random seed `0` are used.
  当前使用 `n_prin_comps=30`、`use_approx_neighbors=False` 和随机种子 `0`。
- Write the continuous score and the automatic call to `obs['doublet_score']` and `obs['predicted_doublet']`; save the score histogram and check the threshold manually.
  将连续分数和自动判定分别写入 `obs['doublet_score']`、`obs['predicted_doublet']`，保存分数直方图并人工检查阈值。
- Exclude cells with `predicted_doublet=True`; only singlets proceed downstream.
  排除 `predicted_doublet=True` 的细胞，只将 singlets 送入下游。

### 5. Merge, normalization and highly variable genes / 合并、归一化与高变基因

- Merge the singlet cohorts with `anndata.concat(..., join='outer', merge='same', index_unique=None)` and confirm again that cell IDs are unique.
  使用 `anndata.concat(..., join='outer', merge='same', index_unique=None)` 合并各 cohort singlets，并再次确认 cell ID 唯一。
- Normalize with `normalize_total(target_sum=10000)` and `log1p()`.
  使用 `normalize_total(target_sum=10000)` 和 `log1p()` 归一化。
- Save the full-gene log-normalized expression into `adata.raw` for marker tests and plotting.
  将全基因 log-normalized 表达保存到 `adata.raw`，供 marker 检验和绘图使用。
- Select HVGs with the configured `hvg.n_top_genes` and `hvg.batch_key`, using `flavor='seurat'`, and save the HVG diagnostic plot and actual parameters.
  使用配置中的 `hvg.n_top_genes`、`hvg.batch_key` 和 `flavor='seurat'` 选择 HVG，保存诊断图和实际参数。

### 6. Scale, PCA and Harmony / Scale、PCA 与 Harmony

- The downstream work object keeps only the 2,000 HVGs.
  下游工作对象只保留 2,000 个 HVG。
- Resolve `REGRESS_COVARIATES` from this run's configuration/sidecar. When enabled, regress `total_counts` and `pct_counts_mt` after log normalization and before scaling; `raw` retains pre-regression expression. Changing this choice is a scientific experiment.
  `REGRESS_COVARIATES` 以本轮配置和 sidecar 为准；启用时在 log normalization 后、scale 前回归 `total_counts` 和 `pct_counts_mt`，`raw` 保留回归前表达。改变该选择属于科学实验。
- Scale with `scale(max_value=10)`, then compute PCA with ARPACK, `PCA_N_COMPS=50` and random seed `0`.
  使用 `scale(max_value=10)` 标准化，再以 ARPACK、`PCA_N_COMPS=50` 和随机种子 `0` 计算 PCA。
- Save the PCA variance plot and the pre-Harmony PCA coloured by cohort; the PCA embedding follows the panel standard in §7 (4.0 in per panel).
  保存 PCA 方差图和 Harmony 前按 cohort 着色的 PCA 图；PCA 嵌入图遵循 §7 的面板标准（每面板 4.0 in）。
- Run Harmony on `X_pca` by `cohort` and write the result to `obsm['X_pca_harmony']`; currently `HARMONY_MAX_ITER=20`, `HARMONY_SIGMA_VALUE=0.1`, the initial cluster count is derived dynamically from the cell count, and the random seed is `0`.
  在 `X_pca` 上按 `cohort` 执行 Harmony，结果写入 `obsm['X_pca_harmony']`；当前 `HARMONY_MAX_ITER=20`、`HARMONY_SIGMA_VALUE=0.1`，初始 cluster 数按细胞数动态计算，随机种子为 `0`。

### 7. Neighbour graph, UMAP and Leiden / 邻接图、UMAP 与 Leiden

- Build neighbour graphs from the original `X_pca` and the post-Harmony `X_pca_harmony` with `N_PCS=30` and `N_NEIGHBORS=15`.
  使用 `N_PCS=30`、`N_NEIGHBORS=15` 分别从原始 `X_pca` 和 Harmony 后 `X_pca_harmony` 构建邻接图。
- Both UMAPs use `UMAP_MIN_DIST=0.5`, `UMAP_SPREAD=1.0` and random seed `0` explicitly, so that candidate runs can be compared item by item.
  两套 UMAP 均显式使用 `UMAP_MIN_DIST=0.5`、`UMAP_SPREAD=1.0` 和随机种子 `0`，便于候选运行逐项比较。
- Save `X_umap_before_harmony` and `X_umap_after_harmony` separately and compare the sample distribution before and after Harmony with identical parameters.
  分别保存 `X_umap_before_harmony` 和 `X_umap_after_harmony`，用相同参数比较 Harmony 前后 sample 分布。
- Check on the Harmony UMAP whether `total_counts` and `pct_counts_mt` still dominate the embedding structure.
  在 Harmony UMAP 上检查 `total_counts`、`pct_counts_mt` 是否仍主导嵌入结构。
- Every intermediate and final embedding uses `Scripts/Common/embedding_plot.py`: an 8 × 8 in square exported canvas (2400 × 2400 px at 300 dpi), including its keys, without tight cropping. A single-panel plot has 4 × 4 in equal-aspect axes; comparisons use smaller square panels in a vertical pair or grid within the same canvas. Before/after panels retain common x/y data windows. Categorical legends are one vertical column on the right; each numerical panel has one external vertical colour bar. These are presentation constants, never searchable analysis parameters. Use `save_embedding()` for publication renderers as well.
  所有中间和最终嵌入图由 `Scripts/Common/embedding_plot.py` 统一导出：含图例的画布固定 8 × 8 in（300 dpi 下 2400 × 2400 px），禁止 tight 裁切。单图绘图区为 4 × 4 in、等比例正方形；对比图在同规格画布内上下排列或网格排列较小的正方面板，before/after 保留共同数据窗口。分类图例在右侧单列；每个数值面板配一条外置竖直色条。发表图辅助脚本也必须调用 `save_embedding()`；这些是展示常量，不是可搜索分析参数。
- Run Leiden on the post-Harmony neighbour graph with `LEIDEN_RESOLUTION=0.8` and random seed `0`, and inspect the CYL/ZCP composition of every cluster（示例样本名 / example sample labels）。
  在 Harmony 后邻接图上使用 `LEIDEN_RESOLUTION=0.8`、随机种子 `0` 运行 Leiden，并检查每个 cluster 的 CYL/ZCP 构成。

### 8. Marker testing and manual annotation / Marker 检验与人工注释

- Compute each cluster's markers with `rank_genes_groups(groupby='leiden', method='wilcoxon', use_raw=True)` and plot the top 20 markers.
  使用 `rank_genes_groups(groupby='leiden', method='wilcoxon', use_raw=True)` 计算每个 cluster 的 marker，并绘制 Top 20 marker。
- Review the annotation against ranked markers, canonical lineage markers, UMAP position, sample composition, QC and rare-population evidence.
  结合 ranked markers、经典谱系 marker、UMAP 位置、样本构成、QC 和稀有群证据审核注释。
- `cluster_to_cell_type` applies only to the cluster set that has actually been reviewed. If clusters are added, lost or renumbered, the notebook stops; silently reusing the old mapping is forbidden.
  `cluster_to_cell_type` 仅适用于当前已经审核的 cluster 集合。实际 cluster 如有新增、缺失或重编号，Notebook 会停止，禁止静默复用旧映射。
- Map Leiden clusters to `obs['cell_type']`; one first-level cell type may merge several Leiden clusters, but the original cluster identity is retained.
  将 Leiden cluster 映射到 `obs['cell_type']`，同一一级 cell type 可以合并多个 Leiden cluster，但原 cluster 身份仍保留。
- The formal mapping is allowed only for `baseline` runs whose actual cluster set matches exactly; a candidate does not inherit the formal labels automatically, even if it happens to produce the same numeric cluster IDs.
  正式映射只允许用于 `baseline` 且实际 cluster 集合完整匹配的情况；candidate 即使恰好得到相同数字编号，也不会自动继承正式标签。
- A candidate must carry a complete automatic proposal. An exact cell-level reference takes priority and records cluster purity/disagreements; marker-panel scoring otherwise keeps the top label and marks a small margin as `proposed_low_confidence` instead of `Unassigned`.
  candidate 必须携带完整自动提议。精确匹配的逐细胞参考表优先，并记录 cluster 纯度与分歧；否则 marker-panel 评分保留 top1 标签，低间隔标为 `proposed_low_confidence`，而不是 `Unassigned`。
- A candidate also saves `tables/candidate_annotation_audit.tsv`, the cluster QC and the cohort fractions; the label column is `candidate_cell_type` and the status is fixed to `candidate_requires_review`.
  candidate 同时保存 `tables/candidate_annotation_audit.tsv`、cluster QC 和 cohort fractions，标签列名为 `candidate_cell_type`，状态固定为 `candidate_requires_review`。

### 9. Annotation plots and targeted review / 注释图与专项复核

- Draw the global cell-type marker dotplot from `adata.raw`; dot size encodes the expressing fraction and colour the mean expression. Its rows are cell types, one per group of the declared panel, with the clusters already merged into them — not clusters, and never samples. Samples are pooled into each row; a per-sample view is a cohort QC figure, not this one.
  从 `adata.raw` 绘制全局 cell-type marker dotplot；点大小表示表达比例，颜色表示平均表达。其纵轴是细胞类型，与声明面板的分组一一对应，cluster 已合并到其中——不是 cluster，也绝不是样本。样本被合并在每一行内；分样本视图属于 cohort QC 图，不是这张图。
- Which of the two dotplots exists follows from the annotation state. A reviewed baseline writes `annotation_marker_dotplot.png` with one row per cell type. A candidate run with a declared panel writes `candidate_annotation_marker_dotplot.png`, the same rows carrying proposed labels. A candidate run with no panel falls back to `candidate_cluster_marker_dotplot.png`, whose rows are the Leiden clusters — that figure is this round's marker evidence for deciding the labels, and it is not the deliverable; a separate annotation revision supplies the cell-type dotplot once labels are proposed or reviewed, preserving its approval state.
  存在哪一张点图由注释状态决定。已审核 baseline 写出 `annotation_marker_dotplot.png`，每行一个细胞类型。声明了面板的 candidate 写出 `candidate_annotation_marker_dotplot.png`，纵轴相同、标签为候选。未声明面板的 candidate 退回 `candidate_cluster_marker_dotplot.png`，纵轴为本轮 Leiden cluster——该图是本轮判定标签的 marker 证据，不是交付物；提出或审核标签后，在独立注释版本中补齐 cell-type 点图，并明确该版本的批准状态。
- Draw marker dotplots for the epithelial and rare clusters separately, and summarize the rare populations' cell counts, QC, doublet score and cohort composition.
  单独绘制上皮相关 cluster 和稀有 cluster 的 marker dotplot，并汇总稀有群的细胞数、QC、doublet score 和 cohort 构成。
- Generate Leiden, cell-type, sample and QC UMAPs on the post-Harmony coordinates; generate the group UMAP only when a verified `obs['group']` exists.
  在 Harmony 后坐标分别生成 Leiden、cell type、sample 和 QC UMAP；只有存在经过验证的 `obs['group']` 时才生成 group UMAP。
- All notebook figures are written as 300 dpi PNGs into `Results/runs/scanpy/<run-id>/scanpy/figures/` and registered in the manifest at the same time.
  所有 Notebook 图片以 300 dpi PNG 写入 `Results/runs/scanpy/<run-id>/scanpy/figures/`，同时登记到 manifest。
- Those PNGs stay comparable across rounds: exploratory and final single-panel annotation figures use the same 8 in square canvas, 4 in square axes, single-column legend and colouring convention. Compare matching layouts; multi-panel overviews have smaller axes.
  中间探索图与最终单面板注释图使用同样的 8 in 方形画布、4 in 正方绘图区、单列图例和着色约定。跨轮比较相同布局；多面板概览的绘图区较小。

### 10. Confirmation, protection and export / 确认、保护与导出

- The final save cell first checks `ANALYSIS_CONFIRMED`; that value may only be enabled after thresholds, dimensionality reduction, clustering, markers and annotation have all been reviewed.
  最终保存单元首先检查 `ANALYSIS_CONFIRMED`；该值只能在阈值、降维、聚类、marker 和注释均已审核后启用。
- Currently `OVERWRITE_DATA_OUTPUTS=False`. When formal outputs already exist, the notebook compares cell IDs and per-cell metadata; on a mismatch it stops instead of overwriting automatically.
  当前 `OVERWRITE_DATA_OUTPUTS=False`。正式输出已存在时，Notebook 会比较 cell ID 和逐细胞元数据；不一致则停止，不自动覆盖。
- Formal outputs are / 正式输出包括：

  - `<output_stem>_confirmed.h5ad`（来源示例 / source example: `rna_e_cyl_zcp_confirmed.h5ad`）
  - `cell_id_cell_type.tsv`
  - `confirmed_parameters.json`
  - `figure_manifest.json`
  - `figures/`

- The H5AD, the per-cell table, the parameter JSON, the figure manifest and the actual figures must all pass the output-consistency check specified later in this README.
  H5AD、逐细胞表、参数 JSON、图片清单和实际图片必须通过 README 后文规定的输出一致性检查。
- A candidate does not write the formal filenames above; it saves `candidate_analysis.h5ad`, `candidate_cell_metadata.tsv`, `candidate_parameters.json`, the candidate audit tables and the candidate figures, and its manifest records `run_kind`, `iteration_id` and `annotation_status` explicitly.
  candidate 不写上述正式文件名，而是保存 `candidate_analysis.h5ad`、`candidate_cell_metadata.tsv`、`candidate_parameters.json`、候选审计表及候选图片；manifest 显式记录 `run_kind`、`iteration_id` 和 `annotation_status`。
- After successful verification, save the executed copy into the results directory and then clear the canonical notebook's embedded outputs, so that large images and historical kernel state are not committed to Git.
  成功验证后将执行副本保存到 Results，再清除 canonical Notebook 的内嵌输出，避免把大体积图像和历史 kernel 状态提交到 Git。

## Execution loop / 执行闭环

### 1. Establish the baseline / 建立基线

Before executing, record / 执行前记录：

- Notebook SHA-256 and Git status. Notebook SHA-256 和 Git 状态。
- Input paths, existence, size and whatever checksum information is available. 输入路径、存在性、大小及可获得的校验信息。
- The formal artifacts already present in the output directory. 输出目录中已存在的正式产物。
- The notebook's current `ANALYSIS_CONFIRMED` and `OVERWRITE_DATA_OUTPUTS` values. Notebook 当前的 `ANALYSIS_CONFIRMED` 与 `OVERWRITE_DATA_OUTPUTS` 值。
- Python kernel and key package versions. Python kernel 和关键包版本。

If the workspace already contains modifications, treat them as the user's work. Do not reset, overwrite or mix them into this round's correction.

若工作区已有修改，将其视为用户工作。不得重置、覆盖或混入本轮修正。

### 2. Clean replay / 干净重放

Execute from the first cell to the last in a compatible Jupyter kernel, in order. A diagnostic replay is preferably saved as a new executed copy or into a new result location, leaving the canonical notebook unchanged.

在兼容的 Jupyter kernel 中从第一单元顺序执行到最后一单元。诊断性重放优先保存为新的执行副本或新的结果位置，canonical Notebook 保持不变。

Verify the upstream analysis first, then decide whether the final save is permitted. Do not mistake an upstream analysis that completed successfully for a computational failure merely because a final-save guard stopped the run.

先验证上游分析，再决定是否允许最终保存。不要因为最终保存保护主动停止，就把已成功完成的上游分析误判为计算失败。

### 3. Layered verification / 分层验证

Check in the following order, and do not claim the next layer passed while a previous one failed:

按以下顺序检查，上一层失败时不宣称下一层通过：

1. **Execution integrity / 执行完整性**：every expected cell has run; there is no unexplained traceback; the kernel and dependencies are identifiable. 所有预期单元已运行；无未解释的 traceback；kernel 与依赖可识别。
2. **Structural integrity / 结构完整性**：cell IDs are unique; the required `obs`, `layers`, `obsm` and `uns` fields exist; matrix and metadata dimensions agree. cell ID 唯一；必要的 `obs`、`layers`、`obsm`、`uns` 字段存在；矩阵与元数据维度一致。
3. **Analytical plausibility / 分析合理性**：the QC flow is explainable; the pre/post-Harmony plots, Leiden, markers, sample composition and final annotation UMAP have been reviewed. QC 流转可解释；Harmony 前后图、Leiden、marker、样本构成和最终注释 UMAP 经过复核。
4. **Annotation completeness / 注释完整性**：every actual cluster has current marker evidence; added, lost or renumbered clusters must be reviewed again; the final annotation UMAP does not obviously contradict the marker, neighbourhood and sample evidence. 每个实际 cluster 都有当前 marker 证据；新增、缺失或重编号 cluster 必须重新审核；最终注释 UMAP 与 marker、邻域和样本证据不存在明显冲突。
5. **Output consistency / 输出一致性**：the H5AD cell count matches the per-cell table; the parameter JSON corresponds to this round's settings; the manifest count and the actual existence of files agree. H5AD 细胞数与逐细胞表一致；参数 JSON 对应本轮设置；manifest 数量和文件实际存在性一致。

A historical baseline can only be used to detect differences; it is not a substitute for this round's verification.

历史基线只能用于发现差异，不能替代本轮验证。

### 4. Annotate every cluster / 注释每个 cluster

A candidate run that still reads `Unassigned` has produced evidence, not a deliverable. Complete the automatic proposal in the same pass and give the user labels to audit rather than clusters to annotate.

candidate 运行结束时若仍为 `Unassigned`，说明它只产出了证据，还不是可交付结果。同一 pass 必须补全自动候选，让用户审核标签，而不是让用户从头注释 cluster。

- Read `tables/candidate_annotation_audit.tsv` together with the marker figures. The table carries each cluster's size, `top1`/`top2`, score margin and Top10 ranked markers.
  结合 marker 图阅读 `tables/candidate_annotation_audit.tsv`：其中含逐 cluster 的细胞数、`top1`/`top2`、score margin 和 Top10 ranked marker。
- Establish one cell type per cluster by looking the ranked markers up as you go: canonical lineage markers first, then the cluster's QC, sample composition and neighbourhood as corroboration. There is no bundled marker panel and no crosswalk to consult — a label has to be defensible from this run's own markers.
  通过实时查询 ranked marker 为每个 cluster 确定一个 cell type：先看经典谱系 marker，再用该 cluster 的 QC、样本构成和邻域佐证。没有内置 marker 面板、也没有可查的对照表 —— 标签必须能由本轮自身的 marker 支撑。
- Write the settled labels into `markers.dotplot_markers` and `markers.cell_type_order` in `config/analysis.yaml`, one group per label, so the dotplot, the ordered legend and the recorded mapping all name the same set. `markers.*` is outside the analysis signature, so adding panels does not invalidate the candidate run.
  将确定的标签写入 `config/analysis.yaml` 的 `markers.dotplot_markers` 与 `markers.cell_type_order`，每个标签一组，使 dotplot、顺序图例与记录的映射指向同一集合。`markers.*` 不属于分析签名，因此新增面板不会使 candidate 运行失效。
- Export agent proposals with `tools/prepare_scanpy_candidate_reference.py` after completing the run-specific worksheet (`cluster`, `cell_type`, `confidence`, `alternatives`, `evidence`). Its table remains unapproved. Only after user review use `tools/record_annotation_review.py --mapping` to record the approved profile.
  完成本轮工作表后，用 `tools/prepare_scanpy_candidate_reference.py` 导出候选逐细胞参考，保留置信度、备选身份和 marker 证据；该表仍未批准。用户审核后才用 `record_annotation_review.py --mapping` 记录已审核 profile。
- Deliver a cell-type dotplot, annotated UMAP, tables and palette for the exact annotation revision; retain cluster-level plots as supporting evidence. Relabelling uses saved coordinates in a new revision directory and does not require reclustering.
  交付与同一注释版本对应的 cell-type 点图、UMAP、表格和配色；cluster 点图保留作佐证。仅修正标签时读取现有坐标、写入新版本目录，无需重新聚类。
- Bind approval to the exact table/cell set. A requested baseline rerun uses a new run ID and `ANALYSIS_CONFIRMED`, with actual membership checked as well as signature/cluster IDs. An approved, verified derived table may instead feed DMR directly after coverage and review-flag filtering are documented and route validation passes.
  批准绑定到确切表格和细胞集。需要 baseline 重跑时使用新 run ID，除签名和 cluster 集合外还核对实际成员；也可将经批准和核验的派生表直接交给 DMR，但须记录覆盖率、review 标记处置和路由验证。

Placeholder labels (`NA`, `Unassigned`, `requires_review`) stay invalid for cell-type DMR, so an uncalled cluster has to be resolved rather than parked.

占位标签（`NA`、`Unassigned`、`requires_review`）在 cell-type DMR 中始终无效，因此未能判定的 cluster 必须解决，不能搁置。

### 5. Final annotation UMAP and parameter self-iteration / 最终注释 UMAP 与参数自迭代

After the preliminary annotation is complete, the final `cell_type` UMAP must be inspected — do not stop at "the code raised no error" or "the label table is complete". At minimum check:

完成初步注释后，必须检查最终 `cell_type` UMAP，而不是在代码无报错或标签表完整时结束。至少检查：

- Whether one cell type is split into severe fragments that no known state can explain. 同一 cell type 是否出现无法由已知状态解释的严重碎裂。
- Whether cell types with clearly incompatible markers are mixed over large areas, or abnormal bridging structures exist. marker 明显不相容的 cell types 是否大面积混合，或存在异常桥接结构。
- Whether every cell type is still separated mainly by sample/cohort, and whether that separation has a known biological basis. 每个 cell type 内是否仍主要按 sample/cohort 分离，且这种分离是否有已知生物学依据。
- Whether rare populations are stable, whether they were absorbed by larger populations, and whether they have independent marker support. 稀有群是否稳定、是否被大群吞并，以及是否具有独立 marker 支持。
- Whether the UMAP structure is driven mainly by `total_counts`, `pct_counts_mt`, doublet score or another technical metric. UMAP 结构是否主要由 `total_counts`、`pct_counts_mt`、doublet score 或其他技术指标驱动。
- Whether the Leiden boundaries, the cell-type merges, the marker dotplot and the local neighbourhoods agree with one another. Leiden 边界、cell-type 合并结果、marker dotplot 与局部邻域是否相互一致。

UMAP is a two-dimensional visualization and does not by itself constitute evidence that an annotation is correct. Marker specificity, plausible continuous states, rare populations and genuine sample biology must not be sacrificed to obtain a more separated, rounder or prettier plot.

UMAP 是二维可视化，不单独构成注释正确性的证据。不能为了获得更分离、更圆或更美观的图而牺牲 marker 特异性、合理的连续状态、稀有群或样本生物学差异。

If a concrete opportunity for improvement is found, small, bounded candidate parameters may be formed autonomously, iterating by changing one parameter family at a time:

若发现明确优化空间，可自主形成小规模、有界的候选参数，并按一次只改变一个参数家族的原则迭代：

| 参数家族 / Parameter family | 可调整内容 / What may be adjusted | 必须重跑的范围 / Scope that must be re-run |
|---|---|---|
| 特征与 PCA / Features and PCA | HVG 数、是否回归协变量、PCA 成分数 / HVG count, whether to regress covariates, PCA component count | 从归一化/HVG 或 PCA 开始，重跑全部下游 / re-run everything downstream from normalization/HVG or PCA |
| Harmony | batch key 已确认前提下的 `nclust`、`sigma`、迭代参数 / `nclust`, `sigma` and iteration parameters once the batch key is confirmed | Harmony、邻接图、UMAP、Leiden、marker、注释 / Harmony, neighbours, UMAP, Leiden, markers, annotation |
| 邻接图 / Neighbour graph | `N_PCS`、`N_NEIGHBORS` | 邻接图、UMAP、Leiden、marker、注释 / neighbours, UMAP, Leiden, markers, annotation |
| UMAP | `min_dist`、`spread` 和其他布局参数 / `min_dist`, `spread` and other layout parameters | UMAP 与图形复核；不能据此声称 cluster 或注释已改善 / UMAP and figure review; this cannot be claimed as an improvement of clustering or annotation |
| Leiden | `resolution` | Leiden、marker、cluster 映射和全部注释复核 / Leiden, markers, the cluster mapping and the whole annotation review |

Every iteration round follows / 每轮迭代遵循：

1. Save the current baseline's parameters, figures, cluster count, marker summary, sample composition and output paths. 保存当前基线的参数、图、cluster 数、marker 摘要、样本构成和输出路径。
2. State the concrete defect to be improved and the rationale for the candidate parameters. 说明要改善的具体缺陷及候选参数的理由。
3. Write the candidate run into an independent iteration directory; do not overwrite the current formal results. 将候选运行写入独立的迭代目录，不覆盖当前正式结果。
4. Re-run from the earliest affected step; when the cluster set changes, discard the old number mapping and recompute markers and the annotation. 从最早受影响步骤开始重跑；cluster 集合变化时废弃旧编号映射并重新计算 marker、重新注释。
5. Compare matching candidate and baseline single-panel exports side by side with fixed colours, category order and plot dimensions — §7 fixes the square canvas at 8 in and the single-panel axes at 4 in. 使用固定配色、类别顺序和相同布局并排比较候选与基线——§7 将方形画布固定为 8 in，单面板绘图区固定为 4 in。
6. Accept the candidate as the new baseline only when the target defect improved and markers, QC, sample structure, rare populations and stability did not visibly degrade. 只有目标缺陷改善，且 marker、QC、样本结构、稀有群和稳定性没有明显退化时，才接受候选为新基线。
7. Update `Report.md` and keep examining the new baseline; start another round when evidence still supports further optimization. 更新 `Report.md`，继续检查新基线；仍有证据支持的优化空间时进入下一轮。

The automatic controller searches around the explicit incumbent with one adjacent change, science parameters first and layout second. Model acceptance is advisory; a candidate needs material improvement without unacceptable regression against both incumbent and initial baseline. Frozen evaluation space/cell IDs and independent-label safeguards support comparison, but do not replace marker, QC and seed-stability review.

自动控制器围绕明确保留的最佳候选做单轴相邻搜索，先 PCA/邻居图/分辨率，后 UMAP 布局。模型接受分数仅作建议；候选需有实质改善，且相对最佳候选、初始基线均无不可接受退化。固定评估空间及全部细胞/特征/元数据身份；拒绝的候选保留，下一轮显式回到最佳候选。范围外的 QC、HVG、Harmony 等变更另建实验，不混入四轴会话。

停止条件由 `config/optimization.yaml` 的预算、patience、局部候选耗尽和升级审核共同决定，不再采用“只试两轮即收敛”。边界或重复参数会尝试其他合法候选。预算停止不等于收敛，布局改善不等于聚类改善；最终仍需 marker、稀有群、sample/QC、种子稳定性及注释/图片复核。每轮 `selection_summary.json` 明确最佳 run、理由和未决检查。完整规则见 skill 的 `references/optimization.md`。

`execution_scope` 记录最早受影响步骤；当前通用执行器仍完整重放 Notebook，不能据此声称已自动复用 QC/PCA 缓存。新版仅用于新计划和新会话，不改变既有结果或活动运行快照。

### 6. Diagnosis and narrow correction / 诊断与窄修正

On failure, first preserve the original error and the minimal reproduction evidence, then classify it:

失败时先保留原始错误和最小复现证据，再归类：

- Environment/dependency: kernel, package versions, resource or file-format problems. 环境/依赖：kernel、包版本、资源或文件格式问题。
- Input: changed paths, content, sample identity or matrix structure. 输入：路径、内容、样本身份或矩阵结构变化。
- Execution state: out-of-order execution, leftover variables, partial output or stale caches. 执行状态：乱序执行、残留变量、部分输出或旧缓存。
- Analysis logic: parameters, data transformations, randomness or changed API behaviour. 分析逻辑：参数、数据变换、随机性或 API 行为变化。
- Biological review: changes in cluster structure, markers or annotation evidence. 生物学审核：cluster 结构、marker 或注释证据变化。

Fix only the minimal scope that direct evidence supports, then re-execute from before the affected step and re-check every downstream invariant. PCA, Harmony, neighbour-graph, UMAP and Leiden parameters may be iterated autonomously as authorized above; if a correction would require changing other canonical notebook logic, overwriting formal data, or changing a biological call that lacks supporting evidence, stop first and request the user's authorization.

每次只修正有直接证据支持的最小范围，然后从受影响步骤之前重新执行，并复查全部下游不变量。PCA、Harmony、邻接图、UMAP 和 Leiden 参数可按上一节授权自主迭代；若修正需要改变其他 canonical Notebook 逻辑、覆盖正式数据或改变缺少证据支持的生物学判定，先停止并请求用户授权。

### 7. Recording and stop conditions / 记录与停止条件

At the end of every round, record the evidence, the conclusion and the next step in `Report.md`. Stop the automatic iteration and hand the decision to the user as soon as any of the following holds:

每轮结束都在 `Report.md` 记录证据、结论和下一步。满足以下任一条件即停止自动迭代并交由用户决定：

- A change to canonical notebook logic outside the authorized parameter families is required. 需要修改已授权参数家族以外的 canonical Notebook 逻辑。
- A confirmed data product would have to be overwritten. 需要覆盖已确认的数据产品。
- The input identity or the intended analysis objective is unclear. 输入身份或预期分析目标不明确。
- Cluster/marker differences cannot be judged reliably from the expression evidence. cluster/marker 差异无法从表达证据得到可靠生物学判断。
- The declared search budget/patience is exhausted, or no unvisited executable local candidate remains. 达到预先声明的搜索预算/patience，或没有未测试且可执行的局部候选；记录停止原因和保留的最佳结果，不宣称全局最优。
- Continuing would significantly increase resource consumption or have irreversible effects. 继续运行会显著增加资源消耗或产生不可逆影响。

## Definition of done / 正式完成标准

Only when all of the following hold may the report be written as "pass":

只有同时满足以下条件，才可在报告中写为“通过”：

- Execution, structure, analysis, annotation and output verification all have evidence, and the final annotation UMAP has completed its plausibility review and the necessary parameter iterations. 执行、结构、分析、注释和输出五层验证均有证据，最终注释 UMAP 已完成合理性审查和必要的参数迭代。
- Every actual cluster carries a cell type established from this round's own marker evidence, recorded in `config/annotation.yaml`, and the user has been asked to confirm the labels that are settled and the ones that are not. No cluster rests at a placeholder label.
  所有实际 cluster 均已基于本轮自身的 marker 证据确定 cell type 并记入 `config/annotation.yaml`，且已请用户确认哪些标签已确定、哪些未确定。没有任何 cluster 停留在占位标签上。
- The delivered annotation dotplot has one row per cell type with the samples pooled into it; a per-cluster dotplot standing in for it means the annotation step did not finish.
  交付的注释点图每行一个细胞类型、样本合并在行内；若以逐 cluster 点图代替，说明注释步骤尚未完成。
- The save behaviour matches the explicit intent of `ANALYSIS_CONFIRMED` and `OVERWRITE_DATA_OUTPUTS`. 保存行为符合 `ANALYSIS_CONFIRMED` 和 `OVERWRITE_DATA_OUTPUTS` 的明确意图。
- Machine-readable outputs agree with the notebook's state in this round. 机器可读输出与 Notebook 本轮状态一致。
- `Report.md` records this round's inputs, code identity, results, differences and unresolved risks. `Report.md` 已记录本轮输入、代码身份、结果、差异和未决风险。

## Batch figure delivery / 同批次图集

New run plans collect this route’s results under `Results/runs/scanpy/<run-id>/figures_comparison/`. The manifest records source identity and artifact checksums. Ordinary and supervised embeddings are separate; DMR heatmaps are existing verified copies. Stage Reports expose rendering and visual-review status independently of analysis completion.
