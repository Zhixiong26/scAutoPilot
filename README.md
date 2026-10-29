# Single-cell Multiomics Analysis

0.16.10：重聚类或更新注释也必须继承已确认的点图样式；独立点图与集合图复用同一套设置，并对照已批准的图做视觉检查。详见[点图样式约定](references/rna-overview.md#preserve-approved-dotplot-style)。保留 0.16.9 的分层顺序、分类说明和紧凑 A–O 排版要求。

0.16.7：完整 Scanpy 总图必须包含 doublet 四图（默认 UMAP 第三排）、注释/QC、组成及每类三基因点图。新计划在 summary 后自动检查交付；缺图、细胞不一致或视觉检查过期时阻止整批完成，数值分析不重复运行。此次修改运行器，历史计划不重写；详见[完整 RNA 图件协议](references/rna-overview.md)。

0.16.6：外部 RNA 参考注释默认按群平均表达做 Spearman 匹配；固定逐格数字热图、每类三基因点图和完整交付检查。同一注释版本的图表集中到一个交付入口，kNN 仅作为明确指定的备选方法。详见[群相关注释协议](references/rna-reference-correlation.md)。本次仅更新文档与项目规则，不修改历史运行器。

0.16.0：新结果按 `Results/runs/<category>/<run-id>/` 自动分类；自定义 DAG 显式选择大类，探索任务共用路径工具。项目级 AGENTS.md 统一正式与探索绘图规范。此次含运行时代码变更，需新执行器和重新验证；历史路径及活动运行不迁移。详见[结果目录与绘图约定](references/result-layout.md)。

0.15.5：整理 methylome 通用分析协议：[图谱与双模态对接](references/methylome-atlas.md)、[共享 marker 分层筛选/展示](references/methylome-markers.md)、[受试者层面疾病与同细胞关联](references/methylome-disease.md)、[四实现 benchmark](references/methylome-benchmark.md)。这是按需读取的分析与验收规范；未新增自动疾病模型或全规模 benchmark 执行器，不升级活动运行快照。

0.15.4：增加旧运行器启动检查、已有产物输入校验、标准 UMAP 重绘工具；调度直接使用符合条件的允许分区，总索引按运行聚合。历史运行不自动升级。

A portable Codex skill for configuration-driven single-cell RNA and DNA-methylation analysis with Scanpy/Harmony, MethSCAn, ALLCools, and MethylVI.

一个由配置驱动的通用 Codex Skill，用于执行 Scanpy/Harmony 单细胞 RNA、MethSCAn VMR/DMR、ALLCools 特征构建和 MethylVI 分析。

## 中文使用说明

0.15.1：新增[配对doublet执行规则](references/paired-doublets.md)：独立捕获文库内
RNA Scrublet与scDblFinder同输入对照后择一 → DNAm MethylScrublet → 不一致/缺失证据复核 → 按cell ID统一过滤。
RNA对照用于方法选择，不合并两工具删除名单，不自动修改历史数据。此版本更新skill协议；旧Notebook的
Scrublet尚未被替换为该双模态执行器，正式采用前必须完成显式部署和smoke测试。

0.15.0：新增本地 Bismark / MethSCAn / vmrseq 加速包的校验、隔离安装和调用适配，详见 [加速后端](references/acceleration.md)。MethSCAn opt5 CPU 复用现有 DAG；Bismark 与 vmrseq 使用独立入口，GPU 需计算节点和相应依赖。不会自动切换已有项目环境。

0.14.1：任务结束钩子支持成功/失败状态及跨项目总索引。通过 `Results/index_targets.json` 显式指定额外 Results 目录，采用锁和原子更新，保留人工内容；失败仅收录诊断证据。新运行须确认冻结执行器包含钩子，旧快照不因 skill 同步自动升级。强制终止需后续核对补记，不宣称后台守护监控。

0.14.0：新增[文献方法接入](references/published-methods.md)，明确 chooseR、clustree、scIB、MethSCAn/ALLCools、DMR 验证及训练预算的方法来源、适用条件与部署状态。新增可选 `propose_methylvi_trial.py`，调用官方 Optuna Random/TPE 提议模型容量参数，冻结输入/划分/训练协议并避免重复。它不训练、不提交、不自动选 winner；其他外部方法须另行部署验证。默认内循环与现有科学结果不变，不升级活动快照。

0.13.0：补齐 [MethSCAn/MethylVI 迭代流程](references/methylation-optimization.md)。新增显式 `methylation_iteration` DAG 路线，复用已完成结果的 PCA/latent，执行有预算的邻居/分辨率/布局搜索、双基线保护和图聚类种子确认；不重新转换 ALLC、不自动重训模型。特征/模型实验由 agent 单独规划。MethylVI latent/hidden/layers 改为配置项，并保存训练历史与实际划分。新建计划后使用，不升级活动快照、不改旧结果。

0.12.0：自迭代改为“保留最佳候选、先聚类后布局”的有界局部搜索。模型接受分数只作建议；多指标退化保护同时对照最佳候选与初始基线，冻结评估空间及全部细胞/特征/元数据身份，跳过重复或不可执行参数。新 round-plan schema v3 显式记录回退基线、单轴变更、搜索阶段及最终复核清单。通用执行器仍完整重放 Notebook，尚未实现自动阶段缓存；MethylVI 更新为分阶段搜索指导，不冒称新增通用自动训练控制器。升级须新计划、新会话，旧科学结果与活动快照不变。

0.11.2：补强 RNA 文件身份、R 代码签名和任务启动校验；修复依赖恢复、dry-run、图集计划身份、自定义 summary 与 RSS 监控。新增产物身份记录、幂等结果索引、繁忙节点排队和独立 VMR＋DMR 模型并行；ALLCools 新缓存绑定 ALLC 来源。不升级活动运行快照、不覆盖旧结果。配置仍为 schema v2；升级后的运行须新建计划，旧记录不会追溯获得新校验等级。

0.11.1：甲基化 DMR 热图统一输出四套；新增 `zscore_mean.png` 及均值/有效细胞数表，任务验收和 figures_comparison 同步要求第四套。均值为每个 cell type 内单细胞 Z-score 均值，至少 3 个有效细胞，不二次标准化。运行代码签名会改变，已有项目仅可在空闲时升级并建立新计划；不得覆盖正在运行的冻结代码。本次针对性计算节点回归测试（作业 312068）2/2 通过，包含实际四图生成；未声称完整测试套件已运行。

### 1. 功能范围

支持以下输入组合：

| 输入 | 可用路线 |
|---|---|
| 仅 RNA | Scanpy/Harmony、QC、聚类、marker 审核表和 UMAP |
| 仅逐细胞 ALLC | MethSCAn VMR、ALLCools、无监督 MethylVI |
| RNA + ALLC | RNA 注释、VMR、分样本/合并样本 DMR、ALLCools、MethylVI |
| ALLC + 有效 `cell_type` | pairwise/pooled DMR、四种热图（原始值、Z-score、压缩色阶、cell-type Z-score 均值）、VMR + 全部 unique pooled-DMR MethylVI |

RNA 输入支持标准 10x filtered matrix 目录、ZIP 和 10x H5。甲基化输入支持逐细胞 `.allc.tsv.gz`，也支持通过显式 glob 选择 ALLCools 风格的 `*_allc.gz`；每个压缩 ALLC 必须具有相邻的 `.tbi`。

默认分析 DAG 从矩阵或 ALLC 开始；显式 Bismark 加速适配器支持上游 FASTQ 比对，但尚无 FASTQ→ALLC 自动衔接。不把示例项目的样本名、细胞数、节点或用户目录作为默认配置。内置的公共 hg38 参考仅在符合条件的人类甲基化项目中启用，并记录来源；其他物种和基因组需要显式配置。

### 2. 安装

```bash
git clone git@github.com:Zhixiong26/scAutoPilot.git \
  "$HOME/scAutoPilot"

mkdir -p "$HOME/.codex/skills"
ln -s "$HOME/scAutoPilot" \
  "$HOME/.codex/skills/scautopilot"
```

如果目标软链接已经存在，请先确认它指向的仓库，不要直接覆盖。安装后开启新的 Codex 会话；可通过以下提示词调用：

```text
请使用 $scautopilot，为我提供的 10x RNA 和逐细胞 ALLC
创建一个新项目。先生成 intake、执行完整 preflight 和 dry-run，不要立即提交正式任务。
```

生成后的项目包含自己的脚本和运行工具，即使之后没有安装本 Skill，也可独立运行。

UMAP 绘图统一规范（v0.8.2）：中间候选、审核后 baseline 与发表图均使用 `Scripts/Common/embedding_plot.py` 的 `save_embedding()`，导出 8×8 英寸方形画布、300 dpi（PNG 2400×2400）。分类图例默认右侧单列，数值色条使用单条竖直布局；禁止 tight 裁切改变画布形状。单图绘图区为 4×4 英寸，对比图在同规格画布内排列较小的正方面板。旧项目与已有图片不会自动改写，升级运行代码后需重新 plan/validate。

### 3. 前置条件

- orchestrator Python 3.9 或更高版本；
- 对输入数据和参考文件具有只读权限；
- 系统中具有 `conda` 或 `mamba`；已有兼容分析环境可以复用，没有时由 Skill 创建；
- Slurm 模式下可以运行 `sinfo`、`scontrol`、`squeue`、`sbatch` 和 `sacct`；
- 甲基化路线必须显式提供 `chrom_sizes` 和 blacklist；TSS BED 可选。Skill 自动计算 SHA-256，若用户声明期望 checksum，则必须一致；
- DMR 路线需要 `review_status: approved`、非空且唯一的 `cell_id`、无占位标签的 `cell_type`、已解决的逐行审核/纳入标记，且至少两个细胞类型达到配置的最小细胞数。

Skill 会先只读发现兼容环境。缺失的 Scanpy/ALLCools、MethSCAn 或 MethylVI 环境会在项目 `.environments/` 下隔离创建、验证并写入 `config/environments.tsv`；不会升级或修改已经存在的共享环境。

### 4. 准备 intake 文件

下面是配对多组学的最小示例。RNA-only 或 ALLC-only 项目可以将另一种输入留空。

`assets/project-template/config/examples/` 另附一份**填好的完整实例** —— `example-ipf-tissue.yaml`（可直接 `init_project.py --intake` 运行）、`example-samples.tsv`，以及记录该项目实测数值的 README。生成的项目不会读取该目录；它的作用是在字段全空之前先看到一个真实填写的样子。其中的 scheduler 段刻意留空：分区、账号、节点名单描述的是你的集群，不是别人的。

```yaml
schema_version: 2
project_id: example_multiome
organism: human

# 使用者数据的当前位置。生成时会把每一项软链接成项目内的 Data/<name>，
# 因此 config/ 里永远不会出现项目外的绝对路径。
data:
  sources:
    - name: Matrix
      path: /shared/lung-tissue/Matrix
    - name: ALLCools
      path: /shared/lung-tissue/ALLCools
    # 也可以直接声明下载来源；生成时不下载，由 tools/link_data.py --execute 取回并校验
    # - name: gse_supplement
    #   url: "https://example.org/gse.tar.gz"
    #   sha256: REPLACE_WITH_SHA256

references:
  genome_id: hg38
  # chrom_sizes 与 blacklist 可以整段省略：技能内置了 GRCh38 的两份公共参考文件，
  # 仅当项目是 human + 有甲基化路线 + genome_id 为 hg38 时自动填入，并在 Report.md 中说明。
  # 要换用自己的文件，就在这里声明（自备 blacklist 需要自己的 blacklist_md5）。
  # chrom_sizes: my_hg38.chrom.sizes
  # blacklist: my_hg38.blacklist.bed
  tss_bed: /reference/hg38_TSS.bed
  tss_bed_sha256: REPLACE_WITH_SHA256

annotation:
  table: Data/annotation/cell_id_cell_type.tsv
  profile: null
  review_status: approved
  cell_id_column: cell_id
  cell_type_column: cell_type

samples:
  - sample_id: sample_A
    condition: control
    batch: batch_1
    include: 1
    rna_path: Data/Matrix/sample_A/filtered_feature_bc_matrix.h5
    rna_format: 10x_h5
    allc_root: Data/ALLCools/sample_A/allc
    allc_glob: "**/*.allc.tsv.gz"
    cell_id_prefix: sample_A
    allc_cell_id_regex: ""
    allc_cell_id_replacement: ""

  - sample_id: sample_B
    condition: treatment
    batch: batch_2
    include: 1
    rna_path: /data/sample_B/filtered_feature_bc_matrix.zip
    rna_format: 10x_zip
    allc_root: /data/sample_B/allc
    allc_glob: "**/*_allc.gz"
    cell_id_prefix: sample_B
    allc_cell_id_regex: ""
    allc_cell_id_replacement: ""

environments:
  - stage: orchestrator
    python: /path/to/analysis-core/bin/python
    executable: /path/to/analysis-core/bin/python
    version_command: /path/to/analysis-core/bin/python --version
    required: 1

  - stage: scanpy_allcools
    python: /path/to/allcools/bin/python
    executable: /path/to/allcools/bin/python
    version_command: /path/to/allcools/bin/python --version
    required: 1

  - stage: methscan
    python: /path/to/methscan/bin/python
    executable: /path/to/methscan/bin/methscan
    version_command: /path/to/methscan/bin/methscan --version
    required: 1

  - stage: methylvi
    python: /path/to/methylvi/bin/python
    executable: /path/to/methylvi/bin/python
    version_command: /path/to/methylvi/bin/python --version
    required: 1

scheduler:
  backend: slurm
  partitions:
    - cpu
  account: null
  allow_nodes: []
  exclude_nodes: []
  max_parallel: 2
  validation_workers: 4
  limited_profiles:
    - methscan_branch
    - dmr
    - feature_builder
    - trainer
  memory_headroom_mb: 4096

analysis:
  methscan:
    min_cells: 6
    dmr:
      raw_p: 0.01
      min_abs_diff: 0.25
      top_per_cell_type: 200
  methylvi:
    feature_targets:
      - 10000
      - 30000
    validation_fraction: 0.1
```

`top_per_cell_type` 只用于 Top-N hypo-DMR 热图。VMR+DMR MethylVI 路线使用满足阈值的全部 unique pooled-DMR，两者不会混用。详细字段见 [configuration.md](references/configuration.md)。

如果使用者没有现成环境，可以省略 `environments` 或保留待创建的目标路径，后续 bootstrap 会自动补齐。

### 5. 生成项目并配置环境

输出目录必须不存在或为空：

```bash
SKILL_ROOT="$HOME/scAutoPilot"
PYTHON=/path/to/python-3.9-or-newer
PROJECT=/work/example_multiome

"$PYTHON" "$SKILL_ROOT/scripts/init_project.py" \
  --intake intake.yaml \
  --output "$PROJECT"

# 确认每个 Data/ 条目都指向声明的来源（只读；加 --execute 才动手）
"$PYTHON" "$PROJECT/tools/link_data.py" \
  --project "$PROJECT"

# 只读生成环境复用/创建计划
"$PYTHON" "$PROJECT/tools/bootstrap_environments.py" \
  --project "$PROJECT"

# 自动创建缺失的隔离环境并更新 environments.tsv
"$PYTHON" "$PROJECT/tools/bootstrap_environments.py" \
  --project "$PROJECT" \
  --execute

# 环境完成后执行日常快速校验

"$PYTHON" "$PROJECT/tools/validate_project.py" \
  --project "$PROJECT" \
  --mode quick \
  --json-out "$PROJECT/preflight.json"

# 首次正式运行或输入/schema/模板变化后执行全量流式校验
"$PYTHON" "$PROJECT/tools/validate_project.py" \
  --project "$PROJECT" --mode full --workers 8 \
  --json-out "$PROJECT/full-preflight.json"
```

`init_project.py` 会按 `data.sources` 把每份输入软链接成 `Data/<name>`，并把解析后的目标写进 `config/project.yaml`；生成时的状态（已就位 / 待下载 / 本机不可见）同时写进根 `README.md` 与 `Report.md`。生成阶段不下载：`url` 来源由 `tools/link_data.py --execute` 取回，先落到隐藏的临时文件、校验 sha256 通过后才移入 `Data/`，失败时 `Data/` 不留任何残留。`link_data.py` 不会覆盖不是它创建的条目。

`link_data.py` 报告 `dangling` 表示链接本身正确、但本机看不到目标路径——这是挂载问题而非链接问题，`validate_project.py` 会明确拒绝这种条目。若某条路径只在计算节点可见，就在执行上下文里校验。

bootstrap 优先复用通过导入测试的已有环境；缺失 profile 默认创建到 `PROJECT/.environments/`。计划和执行证据保存在 `.workflow/environment-bootstrap/`。如需使用其他可写位置，可传入 `--prefix-root`。

quick 模式逐文件检查索引、格式和有界记录；full 模式流式检查全部 ALLC 的列、context、排序和 `mc <= cov`。full 校验会把文件按字节量均衡切块，逐块提交到计算节点（默认 8 块并行 × 每块 4 进程），再在提交主机上合并；不足 32 个 ALLC 文件或本机无可提交目标时改用本机进程池。合并是失败关闭的：缺块、块结果与清单不匹配、或块少报文件都会让整次校验判 invalid 并点名是哪一块；清单未变的块结果会复用，失败后只重跑受影响的块。正式提交要求与当前输入签名一致的 full 证据；`--skip-full-validation` 可在没有证据时跳过并在 plan 与每个 task 记录里留下 `full_validation_skipped: true`，但绝不会伪造证据文件。两种校验都不会修改输入数据或共享环境。

### 6. 规划 DAG 和 dry-run

```bash
"$PYTHON" "$PROJECT/tools/plan_workflow.py" \
  --project "$PROJECT" \
  --routes auto \
  --run-id run_001

"$PYTHON" "$PROJECT/tools/submit_workflow.py" \
  --project "$PROJECT" \
  --run-id run_001 \
  --dry-run
```

`plan_workflow.py` 只生成 DAG，不提交作业。`--routes auto` 根据输入启用可运行路线，也可以显式传入逗号分隔的路线名。显式选择子路线时，只校验该 DAG 实际使用的输入模态、参考文件和环境；例如 `--routes scanpy` 不扫描 ALLC，也不要求 MethSCAn/MethylVI 环境或甲基化参考文件。ALLCools 自动补齐到 MethSCAn filter 的基础链，但不会因此额外运行 smooth/VMR。

Scanpy、MethSCAn、ALLCools 和 MethylVI 均有内置执行适配器，并自动使用 `environments.tsv` 中对应阶段的 Python。`analysis.task_commands` 仅用于专家覆盖；覆盖命令成功后必须写出计划声明的 `<task_dir>/task_outputs.json`：

```json
{
  "artifacts": ["/absolute/path/to/result"]
}
```

`artifacts` 必须是非空列表，且每个路径都必须存在。任务状态会分别保存子进程退出码和证据校验后的包装任务退出码。

### 7. 正式提交

确认 preflight、DAG、task commands 和 dry-run 后，移除 `--dry-run`：

```bash
"$PYTHON" "$PROJECT/tools/submit_workflow.py" \
  --project "$PROJECT" \
  --run-id run_001
```

每个 Slurm 任务在执行 `sbatch` 前都会重新读取 `sinfo`、`scontrol show nodes`、全局 `squeue` 和当前用户 `squeue`。资源报告分别保存 Slurm 可调度 CPU/内存和操作系统观测到的 `CPULoad`/`FreeMem`。

当资源低于正确性所需 floor、分区不存在或 Slurm 查询失败时，不会强行提交。默认按 partition 调度，不固定节点。

**长任务绝不在登录节点执行。** 每个决策点都用同一套主机角色判定：在 Slurm 分配内（`SLURM_JOB_ID` 存在）为 `compute`，本机执行即计算节点；无分配但 `scontrol ping` 有控制器应答为 `submit`（登录节点）；两者皆无为 `standalone`（单机，没有可提交的对象）。在提交节点上，写成 `backend: local` 的项目会被改为 Slurm 提交，而不是就地执行，`submissions.json` 用 `backend_declared` 与 `backend_effective` 记录这次升级，每份 `task_status.json` 记录执行时的角色与 `slurm_job_id`。`run_task.py`、`task_adapter.py` 与 `Methylvi/*/run.sh` 在执行前拒绝，且拒绝属于前置条件失败：退出码 2，不写任何任务证据。登录节点只负责校验、计划、提交、检查与报告，包括资源检查所需的 `sinfo`/`squeue` 查询。若确实需要在当前机器上跑，用 `salloc` 或 `srun --pty bash` 进入分配，而不是加豁免。

单机模式（`standalone`）下 `local` 后端仍可用：使用同一个 DAG，资源为档位目标值按 `scheduler.local.max_threads`、`max_memory` 收紧后的结果，并受并发设置限制。

所有正式结果写入 `PROJECT/Results/runs/<category>/<run_id>/`。同一 run 中断后可再次执行 submit：已完成或仍在调度器中的任务不会重复提交，失败或产物缺失的任务会按依赖恢复。

### 8. 监控和更新报告

```bash
"$PYTHON" "$PROJECT/tools/inspect_run.py" \
  --project "$PROJECT" \
  --run-id run_001

# 需要时（清理 run 目录后、从旧版本迁移后、区域被手工改过后）重建整个运行记录：
"$PYTHON" "$PROJECT/tools/update_report.py" \
  --project "$PROJECT"
```

`inspect_run.py` 在给出运行结论的同时，会把本次 run 的精简记录写入根 `Report.md` 的运行记录区域，因此**多次迭代会累积**而不是互相覆盖；重跑同一 run 会就地更新它自己的记录。同一条记录也会写入本次 run 触及的每个阶段 Report（`Scripts/Scanpy/Report.md` 等）各自的运行记录区域，内容是同一份 summary 按该阶段的任务过滤后的视图 —— 根日志始终是完整记录。这条写入是尽力而为：失败只打印 stderr 警告并附上恢复命令，不改变 run 的退出码。`update_report.py` 是显式路径，写不进去就非零退出；不带 `--run-id` 时从 `.workflow/runs/*/run_summary.json` 全量重建根日志与全部阶段日志（`--run-id` 只用于要求该 run 必须存在）。

根 `README.md` 由 `init_project.py` 依据 intake 与配置**写入一次后冻结**，不反映进度或结果；`Scripts/<Module>/` 下的模块 README 与 Report 正文同样由生成时**一次写入**——`init_project.py` 会在每个阶段文档顶部写入一段标明本项目（项目名、物种、基因组、实际样本、notebook 入口）的上下文块，并把 `<notebook>` 占位符解析为本项目实际入口。阶段 Report 正文中出现的示例样本名与实测数值属于参考项目，由该上下文块明确标注；运行只写入其运行记录区域，不改写正文。

每次运行的证据位于：

```text
PROJECT/.workflow/runs/<run_id>/
├── plan.json
├── preflight.json
├── submissions.json
├── resource_snapshots/
├── resource_usage/
├── tasks/
├── run_summary.json
└── workflow.COMPLETE
```

对应分析结果位于 `PROJECT/Results/runs/<category>/<run_id>/`，不同 run 不共享可写结果目录。

不能只根据作业已经提交或 Slurm 显示 `COMPLETED` 判断分析完成。任务输出、签名、机器可读 summary 和完成标记必须一致。

### 9. 审核并记录细胞类型

Scanpy 给出的 cell type 是**候选**；依赖 cell type 的 DMR 路线只有拿到人工审核过的 profile 才会被规划。审核走两步，第一步生成逐聚类的审核表（`cell_type` 一列已用该聚类自身占多数的标签预填），改完再记录：

```bash
# 1. 生成审核表（一个聚类一行）
"$PYTHON" "$PROJECT/tools/record_annotation_review.py" \
  --project "$PROJECT" --run-id run_001 --worksheet review.tsv

# 2. 修改 cell_type 一列后记录
"$PYTHON" "$PROJECT/tools/record_annotation_review.py" \
  --project "$PROJECT" --run-id run_001 --mapping review.tsv
```

工具会把该 run 的 `analysis_signature` 与聚类集合一起写进 profile（默认 `config/annotation.yaml`，或 `annotation.profile` 指定的路径），因此改过 `leiden.resolution` 或换了数据后旧 profile 自动失效——**重新审核**，不要把映射搬过去。占位标签（`NA`、`Unassigned`、`requires_review` 等）、覆盖不全的审核表、以及会被覆盖的既有审核表都会被拒绝。记录后还需在 `config/project.yaml` 里设置 `annotation.profile`，并把 `annotation.review_status` 改为 `approved`；两者齐备 DMR 路线才会被规划。

**注释在产出它的那一轮自动完成，不停在 `Unassigned`。** candidate 优先按精确 cell ID 使用项目声明的逐细胞参考注释，输出完整着色的候选 UMAP，并逐 cluster 记录多数标签、纯度、竞争标签和本轮 marker；没有完整参考表时，agent 根据本轮 marker、QC、样本构成和必要的 marker 查证自动提出每个 cluster 的最佳标签。低置信候选仍保留生物学标签，同时显式记录置信度和备选身份。用户审核或修正后，批准绑定到具体注释版本和逐细胞表；baseline 重跑为可选步骤，经核验的已批准派生表也可在完成覆盖率、review 标记处置及路由验证后交给 DMR。未经审核的自动标签不得冒充正式结果或进入 cell-type DMR。详见 [Scanpy 与 Harmony](references/scanpy.md)。

### 9.1 Scanpy/UMAP 自动审核迭代 MVP

控制器只搜索 `n_pcs`、`n_neighbors`、Leiden `resolution` 和 UMAP `min_dist`，每轮相对明确保留的最佳候选只移动一个离散步长，退化时显式恢复最佳候选。先搜索前三个科学参数，再调布局；模型建议不能替代多指标非退化检查，边界/重复参数会跳过。五个类型化判断和确定性比较共同记录到不可变 round plan；应用工具检查摘要、基线身份、配置漂移与事务后才写入下一候选。默认 backend 使用官方 `system-one-adapter` 连接本地 OpenAI-compatible 普通 chat model，未配置时明确降级；它不是 Jev。完整规则与命令见 [自动 Scanpy 审核](references/optimization.md)。

### 9.2 实际项目经验回迁：迭代与画图（0.10.0）

参考 IPF_final 的运行记录与脚本，将可复用的决策方法纳入原始 skill：

- [持续迭代与结果选择](references/iteration-practice.md)：明确当前选用结果、单变量候选、固定评价尺度、失败/降级后端、停止条件及注释版本交接；扩展 MethylVI 无监督诊断方法。自动控制器仍只实现 Scanpy 四轴搜索，其他实验需另建计划任务。
- [出版图与热图审查](references/publication-figures.md)：固定注释版本和配色、核验坐标未变、明确 marker 表达尺度与比例分母，审查 DMR 缺失值、归一化和分组展示；生成成功与目检通过分开记录。
- 新增 `tools/prepare_scanpy_candidate_reference.py`：把本轮 marker 工作表转换为未批准的逐细胞参考表，保留置信度、备选身份、marker 证据与来源哈希。生成项目自动携带该工具。
- 汇总图优先使用源 H5AD 的显式 display order/palette，保留 MethSCAn 已保存颜色；缺失或不一致的显式映射会报错。

本版本更新生成器工具和绘图源码，会改变新生成项目的 `code_signature` / `input_signature`。现有项目只在空闲时升级运行代码，随后创建新计划并验证；既有冻结计划和图件保留。IPF_final 的路径、样本、cluster 映射、过滤阈值及手写控制器不作为通用默认值迁入。

### 9.3 全流程优化（0.11.0）

入口区分新建项目、接续分析、迭代选择和只改图；已有项目先读取配置和运行证据，避免重复生成。此次同时修复执行链中的以下问题：

- **输入与元数据**：本地文件声明的 SHA-256 不再丢失，完整校验会核对；无效 intake/source 声明在创建目录前被拒绝。RNA 输出保留清单中的 sample_id、condition、batch，缺失分组保持缺失。
- **可比的迭代**：固定按 cell ID 抽样、评价 k 和随机种子，默认最多 5,000 个细胞；修改图的 neighbors 不会同时改变评价尺度。同源聚类推导的注释不作为独立生物学验证。
- **可恢复的应用**：审核重新核对完成证据，冻结完整配置和来源哈希；会话锁与原子发布避免半轮结果。参数应用保存事务和前后快照，中断后用同一 next-run-id 恢复。停止或要求复核的会话不会被自动继续。
- **DMR 交接**：统一检查大小写占位标签、逐行待审核状态和 dmr_eligible，列名转换保留审核字段。`analysis.methscan.use_rna_annotation: false` 可暂缓 RNA 注释，保留无监督 VMR，关闭细胞类型 DMR。
- **画图与审核**：VMR 保存实际显示顺序/配色；没有可用 RNA 注释时不生成误导性的注释图。关闭视觉审核后不再读取图片或计算视觉指标；可选审核失败会明确记为降级。

升级会改变运行代码签名。仅升级空闲项目，重新 validate/plan，并开新迭代会话。旧 round-plan schema v1 只能保留审计，不能由新版直接应用；项目配置仍为 schema v2。详见[升级约定](references/template-maintenance.md)和[迭代流程](references/optimization.md)。本仓库更新不会自动覆盖已生成项目或另行安装的 skill 副本。

### 10. 测试

```bash
PYTHON_EXE=/path/to/python-3.9-or-newer bash tests/run_tests.sh

/path/to/python-3.9-or-newer \
  "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" \
  "$HOME/scAutoPilot"
```

仓库测试覆盖 RNA-only、ALLC-only、配对多组学、环境 bootstrap、输入数据链接与下载校验、内置参考默认值、完成证据、路线闭包、常见 ALLC 命名、错误 checksum、Slurm 资源选择、主机角色判定与登录节点拒绝、以及 `local` 单机后端。

### 11. 进一步文档

- [配置与 intake](references/configuration.md)
- [环境发现与自动配置](references/environments.md)
- [Scanpy 路线](references/scanpy.md)
- [MethSCAn 路线](references/methscan.md)
- [ALLCools 和 MethylVI 路线](references/methylvi.md)
- [调度与执行](references/execution.md)
- [自动 Scanpy 审核与迭代](references/optimization.md)
- [失败恢复](references/troubleshooting.md)
- [文档与运行证据](references/documentation.md)
- [模板维护与迁移清单](references/template-maintenance.md)、[迁移记录](references/migration-inventory.tsv)

模板内每个模块另有一份完整的中英双语说明与证据台账，随项目一起生成：

- 项目根 `README.md`（生成时一次写入、此后冻结的稳定契约）与 `Report.md`（按 run 累积运行记录，区域格式见 [documentation](references/documentation.md)）
- `Scripts/Scanpy/README.md`、`Scripts/Scanpy/Report.md`
- `Scripts/Methscan/README.md`、`Scripts/Methscan/Report.md`
- `Scripts/Methylvi/README.md`、`Scripts/Methylvi/Report.md`，以及 `allcools/`、`vmr/`、`vmr_dmr/`、`shared/` 各自的 README
- `Scripts/Environment/README.md`、`Scripts/Environment/Report.md`
- `config/examples/README.md` —— 示例项目的实测数值，以及哪些值必须重新推导而不可照搬
- `Supplementary/README.md` —— 内置参考文件的来源、摘要，以及如何替换为自己的文件

`Scripts/Scanpy/Notebooks/` 下有两个 notebook：`scanpy_workflow.ipynb` 是 run DAG 实际执行的入口，`example_ipf_scanpy.ipynb` 是随包附带、**不参与执行**的完整实例，用于展示一次真实的端到端探索（其中的人工注释映射只对那一组 cluster 有效，不可移植）。

## English guide

### Scope

This skill generates auditable projects from standard 10x RNA matrices and indexed per-cell ALLC files. It supports RNA-only, ALLC-only, and paired multiomics projects. Available routes include Scanpy/Harmony, MethSCAn VMR, per-sample and pooled DMR, hypo-DMR heatmaps, ALLCools feature construction, baseline MethylVI, and VMR plus all unique pooled-DMR MethylVI.

The default analysis DAG starts from matrices or ALLC. The optional Bismark acceleration adapter supports explicit upstream FASTQ alignment; automatic FASTQ-to-ALLC handoff is not implemented. No genome, sample label, cell count, filesystem path, Slurm node, or cluster annotation is assumed.

### Install

```bash
git clone git@github.com:Zhixiong26/scAutoPilot.git \
  "$HOME/scAutoPilot"

mkdir -p "$HOME/.codex/skills"
ln -s "$HOME/scAutoPilot" \
  "$HOME/.codex/skills/scautopilot"
```

Start a new Codex session and invoke it explicitly when desired:

```text
Use $scautopilot to generate a project for my 10x RNA and
per-cell ALLC inputs. Create the intake, run preflight and a dry-run, and do not
submit production jobs yet.
```

### Run

Prepare an intake file using the schema shown above, then run:

The intake's `data` block declares where the user's data already lives; generation links each entry into the project's own `Data/`, and the sample paths are then written relative to the project root (`Data/Matrix/...`). Nothing under `config/` points outside the project. `references.chrom_sizes` and `references.blacklist` may be omitted entirely: the skill ships public GRCh38 files under `Supplementary/` and fills in whichever key is blank for a human project with a methylation route — and says so in the generated `Report.md`. A project on another organism or genome keeps the preflight failure that names the reference it must declare, rather than silently inheriting the wrong coordinates.

```bash
SKILL_ROOT="$HOME/scAutoPilot"
PYTHON=/path/to/python-3.9-or-newer
PROJECT=/work/example_multiome

"$PYTHON" "$SKILL_ROOT/scripts/init_project.py" \
  --intake intake.yaml \
  --output "$PROJECT"

"$PYTHON" "$PROJECT/tools/link_data.py" \
  --project "$PROJECT" \
  --execute

"$PYTHON" "$PROJECT/tools/bootstrap_environments.py" \
  --project "$PROJECT" \
  --execute

"$PYTHON" "$PROJECT/tools/validate_project.py" \
  --project "$PROJECT" \
  --json-out "$PROJECT/preflight.json"

"$PYTHON" "$PROJECT/tools/plan_workflow.py" \
  --project "$PROJECT" \
  --routes auto \
  --run-id run_001

"$PYTHON" "$PROJECT/tools/submit_workflow.py" \
  --project "$PROJECT" \
  --run-id run_001 \
  --dry-run
```

Generation links every declared `data.sources` entry into the project's own `Data/<name>` and writes the resolved target into `config/project.yaml`; the state at generation time (in place, pending download, or not visible from this host) also goes into the root `README.md` and `Report.md`. Generation never downloads: a `url` source is fetched by `tools/link_data.py --execute`, which streams it to a hidden temporary file, verifies the declared sha256, and only then moves it into `Data/`. A failed fetch leaves nothing behind. `link_data.py` never overwrites an entry it did not create.

A `dangling` state from `link_data.py` means the link is exactly right but its target is unreachable from this host — a mount question, not a link question. `validate_project.py` refuses such an entry by name, so check data reachability in the execution context.

The bootstrapper reuses compatible environments read-only and creates missing profiles under `PROJECT/.environments/` from bundled versioned specs. It verifies imports or executables before updating `config/environments.tsv`; it never upgrades a discovered shared environment.

Review the preflight report, DAG, and resource plans. Built-in adapters cover Scanpy, MethSCAn, ALLCools, and MethylVI and select the declared stage environment. Explicit route subsets validate only the input modalities, references, and environments used by their closed DAG. `analysis.task_commands` is an expert override, not a required setup step. A successful override must create `<task_dir>/task_outputs.json` with a non-empty `artifacts` array of existing absolute paths; child-process and wrapper-task return codes are recorded separately.

To execute an approved run, repeat `submit_workflow.py` without `--dry-run`. Production submission requires matching full-validation evidence and creates it when absent. A full ALLC validation splits the files into byte-balanced chunks, submits one job per chunk to compute nodes — 8 in flight with 4 processes each by default — and merges them on the submitting host; below 32 ALLC files, or with nothing to submit to, it reads in place through a process pool. The merge is fail-closed: a missing chunk, a chunk result that does not match its manifest, or a chunk that accounts for fewer files than it was handed makes the whole validation invalid and names the chunk, and a chunk whose manifest is unchanged is reused rather than resubmitted. `--skip-full-validation` submits when no evidence is on disk and records `full_validation_skipped: true` on the plan and every task record, writing no evidence file. `inspect_run.py` reports the evidence state and the ALLC counts beside the verdict, so a project whose selected routes read no ALLC file cannot pass for a checked one. Each Slurm task receives a fresh resource query immediately before submission. Results are isolated under `Results/runs/<category>/<run_id>/`, and re-submission resumes incomplete work.

**Long-running tasks never execute on a login node.** Every decision point resolves the same host role: `compute` inside a Slurm allocation (`SLURM_JOB_ID` is set), where the local executor is itself a compute node; `submit` when no allocation exists but `scontrol ping` reports a controller UP; `standalone` when neither holds, and there is nothing to submit to. On a submit host a project configured `backend: local` is submitted to Slurm rather than executed in place, `submissions.json` records that as `backend_declared` beside `backend_effective`, and each `task_status.json` records the role and `slurm_job_id` the task saw. `run_task.py`, `task_adapter.py`, and `Methylvi/*/run.sh` refuse before executing, and a refusal is a precondition failure: exit 2, no task evidence written. The login node validates, plans, submits, inspects, and reports — including the `sinfo`/`squeue` queries the resource check performs. To run work on the machine you are on, enter an allocation with `salloc` or `srun --pty bash` rather than granting an exemption.

On a standalone machine the `local` backend remains available: the same DAG, with resources clamped to `scheduler.local.max_threads`/`max_memory` and floored against the profile.

`assets/project-template/config/examples/` carries a completed intake (`example-ipf-tissue.yaml`, runnable directly with `init_project.py --intake`), the same rows as a generated manifest, and a README recording one study's observed magnitudes and the values that must be re-derived rather than copied. Generated projects never read it. Its scheduler block is deliberately empty: partitions, accounts, and node lists describe your cluster, not someone else's.

The template also ships standalone `run_*.sbatch` and `submit_*.sh` wrappers that run one stage without a plan, for exploring a stage, smoke testing a change, or recovering a single stage of a completed run. They resolve resources from the same named scheduler profiles the DAG uses and carry no site directive, but they produce no `task_outputs.json` and are never a run's completion evidence. The MethylVI route runners additionally require an explicit `SCMO_STANDALONE_ACK=1`, which those wrappers set; a direct `run.sh` call is never granted it implicitly. That acknowledgement is about provenance, not about host: it does not make a login node a legal place to run, and the runners refuse one. The `.sbatch` wrappers are sbatch entry points — submit them rather than bashing them by hand outside an allocation.

### Further documentation

- Skill-level references: [configuration](references/configuration.md), [environments](references/environments.md), [Scanpy](references/scanpy.md), [MethSCAn](references/methscan.md), [ALLCools and MethylVI](references/methylvi.md), [execution](references/execution.md), [troubleshooting](references/troubleshooting.md), [documentation](references/documentation.md), [template maintenance](references/template-maintenance.md).
- The project root carries `README.md` — the stable contract, written once at generation and frozen — and `Report.md`, which accumulates one concise record per run in a tool-owned region (format in [documentation](references/documentation.md)).
- Every packaged module also carries its own bilingual README and evidence ledger, generated with the project: `Scripts/Scanpy/`, `Scripts/Methscan/`, `Scripts/Methylvi/` (plus `allcools/`, `vmr/`, `vmr_dmr/`, `shared/`), and `Scripts/Environment/`. Generation writes each one once, adding a context block that names this project, its organism, genome, actual samples and notebook entry; the prose below it — including the reference project's example sample names and worked numbers — is labelled as the reference project's and is never rewritten. The stage Report additionally carries its own run-log region, refreshed per run with that stage's tasks only, so a reader of `Scripts/Scanpy/Report.md` does not have to read the MethylVI runs around it.
- `Supplementary/README.md` records the provenance and digests of the bundled reference files, and how to override them.
- `Scripts/Scanpy/Notebooks/scanpy_workflow.ipynb` is the notebook the run DAG executes. `example_ipf_scanpy.ipynb` beside it is a complete worked example that is never executed; its reviewed cluster-to-cell-type mapping is valid only for that example's exact cluster set and must not be transplanted.

### Inspect completion

```bash
"$PYTHON" "$PROJECT/tools/inspect_run.py" \
  --project "$PROJECT" \
  --run-id run_001

# When needed — after pruning run directories, migrating an older project, or hand edits:
"$PYTHON" "$PROJECT/tools/update_report.py" \
  --project "$PROJECT"
```

`inspect_run.py` records the run's verdict and, at the same time, refreshes that run's concise entry in the root `Report.md` run log, so successive iterations **accumulate** instead of overwriting each other; re-inspecting a run updates its own entry in place. The same entry also goes into the run-log region of every stage Report the run touched, filtered to that stage's tasks — a per-stage view of one corpus of summaries, not a second source of truth. That write is best effort: a failure prints a stderr warning with the recovery command and leaves the run's exit code untouched. `update_report.py` is the loud path and exits non-zero when it cannot write; without `--run-id` it rebuilds the root log and every stage log from `.workflow/runs/*/run_summary.json` (`--run-id` only requires that one run to exist).

The root `README.md` is written once by `init_project.py` from the intake and configuration and is **frozen** afterwards: it reports no progress and no results. The module READMEs and the prose of the module Reports under `Scripts/<Module>/` are written once at generation too, each carrying a generated context block naming this project, its organism, genome, actual samples and notebook entry. The example sample names and measured numbers in that prose belong to the reference project and are labelled as such; rewriting them into statements about this project would fabricate evidence. Only the stage Reports' run-log regions are updated by a run.

A run is complete only when validated outputs, signatures, machine-readable summaries, and completion markers agree. Slurm submission or a `COMPLETED` scheduler state alone is not sufficient.

### Review and record cell types

Scanpy's cell types are **proposals**. The cell-type DMR routes are planned only against a profile a human has reviewed, and the review is two passes: the first writes a per-cluster worksheet whose `cell_type` column is pre-filled with that cluster's own majority label, and the second records what you changed.

```bash
# 1. a worksheet, one row per cluster
"$PYTHON" "$PROJECT/tools/record_annotation_review.py" \
  --project "$PROJECT" --run-id run_001 --worksheet review.tsv

# 2. after editing the cell_type column
"$PYTHON" "$PROJECT/tools/record_annotation_review.py" \
  --project "$PROJECT" --run-id run_001 --mapping review.tsv
```

The tool writes the run's `analysis_signature` and cluster set into the profile alongside the labels (to `config/annotation.yaml`, or to `annotation.profile` if it names a path), so a profile recorded for one set of parameters cannot be reused after `leiden.resolution` changes or the data is re-run — review again instead of transplanting the mapping. Placeholder labels (`NA`, `Unassigned`, `requires_review`, and similar), a worksheet that does not cover the run's clusters exactly, and an existing worksheet it would overwrite are all refused. Recording is not enough on its own: set `annotation.profile` in `config/project.yaml` and set `annotation.review_status` to `approved`, and only then do the DMR routes become plannable.

**The first pass auto-annotates; it does not stop at `Unassigned`.** A candidate first uses an explicitly supplied per-cell reference when exact cell IDs cover the analysed cells, recording cluster consensus, purity, disagreements, and current-run markers. Without a complete reference, the agent assigns every cluster from current-run markers, QC, sample composition, and marker references, preserving low confidence and alternatives rather than withholding a label. It delivers a fully coloured candidate UMAP for user review. Approval binds the exact annotation revision and cells. A baseline rerun is optional when a verified approved derived table is the downstream input; coverage, review flags and route validation still apply. Automatic candidate labels never masquerade as formal annotations or feed cell-type DMR. See [Scanpy and Harmony](references/scanpy.md).

See the linked references above for configuration, route-specific behavior, resource selection, troubleshooting, and evidence contracts.

## Batch comparison figures (0.9.0)

New runs include `figures_comparison` after analysis and before the final summary. All seven routes receive explicit coverage, including native ALLCools UMAP and existing DMR heatmaps. Delivered images and tables are checksum-verified, interrupted publication is recoverable, and visual review has a separate status. See [delivery and upgrade instructions](references/figures-comparison.md). Set `analysis.figures_comparison.enabled: false` before planning to disable the task.
