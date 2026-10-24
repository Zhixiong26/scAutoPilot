# 文献方法接入：选参、验证和效率 / Literature-backed optimization

Use when choosing an iteration strategy, interpreting stability/integration scores,
or proposing an outer model experiment. Consult the relevant section, not every
method on every run. Source/API review: 2026-10-17. Pin the implementation version
or repository commit actually executed; a citation is not execution evidence.

## 方法路由与真实接入状态

| 环节 | 优先考虑的方法 | 本 skill 中的状态与用途 |
|---|---|---|
| 配对 RNA/DNAm doublet | RNA Scrublet/scDblFinder同输入比较后择一 + DNAm MethylScrublet | 按捕获文库检测、复核不一致证据、统一过滤；[协议与迁移边界](paired-doublets.md)，不取两RNA工具删除并集 |
| PCA/邻居/Leiden 候选确认 | chooseR 重采样稳健性 | 外部方法协议；当前 ARI/Jaccard 种子检查不是 chooseR |
| 分辨率诊断 | clustree | 外部可视化协议；不等于自动选最佳 resolution |
| Harmony/整合质量 | scIB / scib-metrics | 外部 benchmark 协议；当前近似 sample-mixing 指标不是官方 iLISI |
| MethSCAn VMR/表示 | MethSCAn 原文的区域、残差及 iterative-PCA 方法 | 原生流程已有；比较特征/缺失处理需新实验 |
| ALLCools 特征 | 官方 bin/覆盖/变异特征流程 | 已有路线；bin size/特征数是独立对照，不套 RNA HVG |
| MethylVI 模型容量选参 | Random Search → Optuna TPE | **新增可执行提案器**，只提议，不提交/训练/自动接受 |
| 大规模训练预算 | Hyperband/ASHA；scvi autotune | 可选部署方案，**尚无本地自动调度接入**，先做兼容性试验 |
| 疾病 DMR | dmrseq 区域推断、DSS 位点效应检查 | 外部推断/敏感性协议，不是最大化显著性的方法 |
| UMAP 展示 | UMAP 官方参数与已有保真度检查 | 只优化布局；加权图不是无监督聚类验证 |

“外部协议”表示 agent 可在用户授权范围内另外部署官方实现；不表示已安装、已运行
或进入现有 controller。没有依赖时记录 `not_run`，不拿近似指标替代后沿用方法名称。
本页组合这些方法的顺序、预算和保护条件是 **scAutoPilot 工程策略**，不是某篇论文
已验证的端到端优化器，也不保证全局最优。

## 先选择问题与证据，再选择搜索算法

1. 冻结细胞、特征、独立验证标签、统计单位、比较目的、预算和评价协议。
   分开研究 upstream 表示、graph/partition 和 layout。只有发现 upstream 缺陷，
   才升级到更贵的特征重算或模型重训。
2. 少量有解释性的单家族对照先走现有内循环。需要跨组合探索时，启用独立外循环，
   不往已有不可变四轴 session 塞入新的参数或另一种选择规则。
3. 小预算/低维候选可枚举或 Random Search；观察足够后才使用 TPE。不要把 TPE
   的 startup random 阶段称为已完成贝叶斯优化，也不要无证据承诺比有界搜索更快。
4. 确认阶段使用未参与筛选的 seeds/subsamples；若有独立验证样本，将其留到最终
   比较。按 donor 留出用于评估跨供者泛化时，特征发现和训练也不能看到该 donor。
   仅按细胞随机划分不能声称跨供者泛化；本 skill 尚未自动实现 donor-held-out 训练。
5. 输出各指标和 trade-off，保留 incumbent。稳定性、稀有群和生物学证据冲突时
   返回 `review_required`，不要用单一加权总分掩盖问题。正式标签仍需显式复核。

Random Search 的依据是 [Bergstra & Bengio, JMLR 2012](https://jmlr.org/papers/v13/bergstra12a.html)；
TPE 的依据是 [Bergstra et al., NeurIPS 2011](https://proceedings.neurips.cc/paper/2011/hash/86e8f7ab32cfd12577bc2619bc635690-Abstract.html)。
这些是通用优化方法，不是 IPF 数据上效果更好的证明。

## Scanpy：不要只凭 silhouette 选择细胞划分

### 配对双模态检测，不叠加多个 RNA 工具

按独立捕获文库使用相同原始RNA counts对照Scrublet与scDblFinder，择一作为RNA检测器；使用DNAm mc/cov执行
ALLCools MethylScrublet；两边完成评分前不按RNA doublet结果预先删除DNAm细胞。
集中复核不一致及缺失证据，最终按cell ID同步过滤，保留九列决策表。
两个RNA工具用于方法选择，不取并集、交集或多数投票删除；不增加更多工具或开发替代检测方法，不把两工具一致当独立真值。
执行边界、官方来源、缺失状态和决策表见[配对doublet协议](paired-doublets.md)。

### chooseR：确认分辨率和表示候选的稳健性

从少量完成的候选开始，用 [chooseR 原文](https://doi.org/10.1186/s12859-021-03957-4)
及[作者实现](https://github.com/rbpatt2019/chooseR)做 subsampling/reclustering，
记录共聚频率、逐 cluster 稳健性及官方选择结果。预先冻结子采样比例、次数、seed、
候选范围和实际重算阶段。论文中使用过 100 次、每次 80% 细胞；这是参考设置而非
每个数据集必需的硬编码，减少次数应标为 pilot，不声称具有同等精度。

使用相同 subsamples 比较候选；从最早受扰动步骤重新估计。固定 PCA/latent 只重建
图时，报告 **conditional graph stability**，不是完整流程稳定性。重新训练模型与
重跑图的 seeds 分开。现有 0.13 内循环只做种子 ARI/逐群 Jaccard，不能改名 chooseR。
Scanpy/MethylVI 的适配若偏离作者实现，写 `chooseR-inspired adaptation` 并列出差异；
甲基化需单独验证适用性。共聚矩阵有二次内存开销，只对 shortlist 在 compute 上运行。

### clustree：查看分裂发生在哪里

固定细胞和 graph，仅改变 Leiden resolution；导出 cell-ID 对齐的数值型 cluster 列
（如 `res_0.4`, `res_0.6`, `res_0.8`）。使用官方
[`clustree()`](https://lazappi.github.io/clustree/articles/clustree.html)绘图，结合 marker、
sample/QC overlay 检查稳定分支和反复跨群流动。不同 graph/PCA 的结果不能装成单纯
resolution 树；节点编号不是生物学标签。不把视觉分支稳定当成统计显著性。
方法出处：[Zappia & Oshlack, GigaScience 2018](https://doi.org/10.1093/gigascience/giy083)。

### scIB：同时看 biology conservation 与 batch removal

用 [scIB 原文](https://www.nature.com/articles/s41592-021-01336-8) 与
[官方 scib-metrics](https://scib-metrics.readthedocs.io/en/stable/)评估适用于当前输出
类型的指标；固定输入及 subsample，不在 2-D UMAP 上代替原表示评分。分别报告
cell-type ASW/isolated-label、batch ASW/LISI 等实际算出的指标与缺失原因，不能把
现有固定 k 的 inverse-Simpson approximation 当官方 iLISI。

独立标签不足时，label-dependent 项标为诊断或不执行。RNA 注释用于 VMR+DMR 特征
选择后，再以它评估一致性属于依赖证据。donor 与 disease 完全混杂时，不能以全局
混合最高为目标；看有足够支持的同类型/同条件子集并报告不可识别的因素。论文总分
权重不是项目通用最佳权重；RNA/ATAC benchmark 也不是 DNA 甲基化的直接验证。

## MethSCAn / ALLCools：优先解决覆盖与特征定义

[MethSCAn 原文](https://www.nature.com/articles/s41592-024-02347-x)比较了区域定义、
甲基化量化与降维策略，并提出 iterative PCA 处理缺失。沿用原始方法含义，而非
给比例矩阵套 RNA log-normalize/HVG。独立改变 VMR 选择、smoothing 或表示构建；
保存覆盖率、缺失率、区域长度/数目、细胞保留率和下游稳定性。
模板中的 `iterative_pca_impute()` 是本项目的实现适配；不能据相同方法名称声称
与论文代码逐行等价。记录实际停止条件、PCA solver、参数和实现版本。

特别注意：[官方 `scan` 文档](https://anders-biostat.github.io/MethSCAn/commands.html)
中的 `var-threshold=0.02` 表示选择最具变异的 **2% genomic bins** 再合并，不是
“方差绝对值 > 0.02”，也不是 p 值。paper 和当前 CLI 的默认 stepsize 不一定相同；
记录实际版本、`--help` 和命令。smooth bandwidth 与 scan bandwidth 分开记录。

可以增加遮盖部分**已观测值**的重建检查，但这属于本项目额外适配：先遮盖再拟合，
不能先用完整数据 impute 再遮盖；自然缺失不是可验证真值，也不能作为 0。报告覆盖
层次下的误差与稀有群，不仅是平均误差。若要推断泛化，特征发现也应限制在训练集。
此遮盖验证尚无内置 executor；不要据文档宣称已经执行。

[ALLCools 官方实现](https://github.com/lhqing/ALLCools)用于 bin/覆盖/变异特征步骤。
2 kb/5 kb、不同 feature counts、VMR-only 与 VMR+DMR 分别建模比较：固定细胞和
预算，报告每套特征的可观测性。不能直接拿不同特征集的 ELBO 判胜；也不能把普通
ALLCools 矩阵聚类写成 MethylVI。原有可复用阶段见
[依赖边界](methylation-optimization.md#dependency-and-reuse-boundary)。

## MethylVI：成熟搜索器接入外循环，不代替科学验收

[MethylVI 官方模型说明](https://docs.scvi-tools.org/en/1.3.3/user_guide/models/methylvi.html)
要求 mc/cov 区域计数；latent 不是按解释方差排序的 PCs。先在全 latent 上筛 graph，
有模型缺陷才增加容量实验。`n_latent`、`n_hidden`、`n_layers` 已有正式配置接口。

新增 `tools/propose_methylvi_trial.py` 使用 **Optuna 官方 RandomSampler/TPESampler**
产生一个外循环容量组合；依据
[Optuna 论文](https://arxiv.org/abs/1907.10902)与
[官方 ask/tell 接口](https://optuna.readthedocs.io/en/v4.5.0/tutorial/20_recipes/009_ask_and_tell.html)。
已测依赖为 `optuna==4.5.0`；仅装入单独方法环境，不升级共享训练环境。该脚本没有
Ray、后台调度、训练、模型晋升或参数文件写入；所有新训练仍经独立 signed DAG。
不要把它当成已集成 `scvi.autotune` 的 MethylVI 实验。

### 提案器契约

请求 JSON 含 `protocol` 和 `trials`。protocol 字段：

- `schema_version: 1`, `sampler: random|tpe`, `seed`, `max_trials`（含 failed/pending），
  `n_startup_trials`；小预算下保留 Random Search，不为了用 TPE 强行扩大计算。
- `space`：仅允许 `n_latent` / `n_hidden` / `n_layers` 中至少一项，值为递增、去重的
  正整数列表。未搜索的容量参数写进固定训练清单。允许同一容量家族组合变化，**不适用
  于四轴 Scanpy session 的单轴修改规则**。不搜索 QC、标签、DMR p 值或 supervised weight。
- `objective: {name: elbo_validation, direction: minimize, reduction: last}`；也可显式选
  `validation_loss` 和 `min`。确认实际日志指标方向，固定 reducer、epoch/warmup/early-stop
  协议。仅验证集用于搜索；test set 不用于调参。不同 early-stop 步数需如实报告。
- `bindings`：`counts_manifest`, `cell_ids`, `feature_ids`, `split_manifest`,
  `fixed_training` 各给 `{path, sha256}`，绑定小型来源清单、真实顺序/划分和固定训练
  协议。路径相对 request；程序转为绝对路径。换特征/细胞/划分必须新协议。
  `fixed_training` 包含训练代码/包版本、模型训练 seed、epochs/warmup/early-stop、
  batch size、优化器等未搜索设置；protocol 的 `seed` 仅用于提案随机数。

一个起步例子（哈希需替换为真实文件 SHA-256，不提供默认数据或默认最佳参数）：

```json
{
  "protocol": {
    "schema_version": 1, "sampler": "tpe", "seed": 0,
    "max_trials": 12, "n_startup_trials": 5,
    "space": {"n_latent": [10, 20, 30], "n_hidden": [64, 128, 256]},
    "objective": {"name": "elbo_validation", "direction": "minimize", "reduction": "last"},
    "bindings": {
      "counts_manifest": {"path": "counts_manifest.json", "sha256": "ACTUAL_SHA256"},
      "cell_ids": {"path": "cell_ids.tsv", "sha256": "ACTUAL_SHA256"},
      "feature_ids": {"path": "feature_ids.tsv", "sha256": "ACTUAL_SHA256"},
      "split_manifest": {"path": "split_manifest.json", "sha256": "ACTUAL_SHA256"},
      "fixed_training": {"path": "fixed_training.json", "sha256": "ACTUAL_SHA256"}
    }
  },
  "trials": []
}
```

在小型 compute allocation 中调用（旧项目先安全升级 idle 工具；source 可用 `scripts/`）：

```bash
python tools/propose_methylvi_trial.py --request method_request.json --output proposal_001.json
```

1. 输出 `proposal`、实际 Optuna 版本/采样阶段、协议摘要和 `next_request`。单个协调者
   保存 `next_request` 为下一请求，先登记 pending，再规划/提交候选。相同 request 可重放，
   **不是**共享持久 study；不要让并发协调者使用旧 ledger 重复提交。多个训练任务可并行。
2. 先按标准 DAG 核实完成、counts 和实际划分。现有 trainer 只导出 split IDs，
   **不接收本提案器的 split manifest 来强制划分**；必须逐 trial 比对。若同 seed 下
   实际 split 不同，拒绝喂给同一 study，先实现/验证固定划分或另开协议。
3. 从训练历史按固定 reducer 提取 value；另存只读 evidence JSON（含该 trial 的
   `id`, `parameters`, `state`, `protocol_sha256`, `value`，并补源 run/task、历史文件
   hashes、预算和划分核对）。把 ledger pending 改为 complete，加入 value 和
   `evidence: {path, sha256}`。失败记录为 failed 并附同结构错误证据，不伪造低/高 loss。
   提案器只核对小文件 hashes/对应字段；**不能替代源任务完成或语义审核**。
4. 使用完整 ledger 再提案。已有 complete/failed/pending 参数不会重新返回；64 次重复
   抽样后仅返回明确标注的未访问网格 fallback。预算/候选耗尽不是全局收敛。
5. 验证 loss 只筛模型候选，不能自动成为最终 winner。shortlist 还需同预算 graph
   评估、独立训练 seeds、覆盖/批次/稀有群和生物学复核；原始/加权 UMAP 分开交付。

### 多保真预算：先预留接口，不能冒称已经接通

[Hyperband](https://jmlr.org/papers/v18/16-558.html)及
[ASHA](https://proceedings.mlsys.org/paper_files/paper/2020/hash/a06f20b349c6cf09a6b171c71b88bbfc-Abstract.html)
可给差的候选提前停止；
[scvi-tools autotune API](https://docs.scvi-tools.org/en/1.3.3/api/reference/scvi.autotune.run_autotune.html)
提供独立框架，但 scVI 示例不等于当前 METHYLVI/MuData 路线已兼容。需要先测试真实
class、注册数据、validation metric、checkpoint 恢复及 Slurm 资源限制。当前提案器
使用 NopPruner，无自动 early-pruning。未来启用时，warmup 前不剪枝，rung 按可比
训练资源，保留完整训练对照；新机制需 isolated smoke、签名/配置和预算审核。

## DMR：敏感性检查不能变成寻找最小 p 值

疾病比较按 donor × cell type 聚合原始 mc/cov，使用
[dmrseq](https://bioconductor.org/packages/release/bioc/vignettes/dmrseq/inst/doc/dmrseq.html)
做有生物学重复的区域推断，并用
[DSS](https://bioconductor.org/packages/release/bioc/vignettes/DSS/inst/doc/DSS.html)检查位点效应。
两法共享数据，不是独立实验验证；区域与位点的统计量/FDR也不混写。固定对比、方向、
设计矩阵和预设 coverage/effect 规则；报告效应一致性、供者支持、覆盖及边界稳定性。
留一供者属于额外敏感性协议，需保留可估计设计。不能按 DMR 数/热图对角线强度调 FDR。
这些不是当前 pooled-celltype MethSCAn DMR 的替换器；选择或增加推断引擎需独立计划。

## 统一记录和交付

每个外部方法实验留 `method_protocol.json`：method/source DOI+URL、实现 version/commit、
`implementation_scope`（official / adapted / policy_only）、输入与注释 hash、cell/feature
和 split identity、统计单位、参数候选、优化目标及禁用目标、预算、失败/停止规则。
再保存全部 trial table、测量与依赖状态、计算资源、shortlist/拒绝理由及确认结果。
官方可选依赖缺失写 `not_run`；适配测试通过不等于真实数据有效性通过。

图形仍遵守普通/监督分离与 DMR 四视图规则；完成的图更新 Results 索引。所有方法
先使用独立环境和新 run；不在活动快照上升级包、改阈值、覆写分组或回填“成功”。
UMAP 本身的展示参数参考[官方说明](https://umap-learn.readthedocs.io/en/latest/parameters.html)，
不能用二维分离度替代以上验证。
