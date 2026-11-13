# Rebuttal 全部现有实验结果

**新一轮运行状态：**[24 小时单次补跑、48 个预测 CCI 部署及修复核验](once24h-v15.md)（2026-11-13 20:17 UTC）。下文为此前冻结的结果，尚未用新一轮未完成数据覆盖。

**当前准确率采集：2026-11-14 02:07 UTC+8。成本/受控/信息损失采用11月12日冻结报告，并分别标注。未新增推理或评分来生成本报告。**

此处先汇总结果，不展开超时诊断。科学单位为题目×repeat×方法，重试不是seed；既有completed全部保留，不按正确答案筛选。缺失/未评分不填0，明确任务预算耗尽仍记0。mean±std为三个repeat有效样本准确率的均值±样本标准差（ddof=1）；有效分母不满300时不是完整100×3。保留了旧轮数配置的完成结果，不能把所有合并结果都标为500轮。

## 1. BC多模型 / 双harness

单元格：mean±std (%)，括号内有效题次N/300。各方法分母不同，不能直接据此宣称公平排名。DeepSeek模型为deepseek-v4.1-flash-1017，Gemini为历史归档标签。

|方法|Gemini＋Hermes|DeepSeek＋Hermes|DeepSeek＋DSH|
|---|---:|---:|---:|
|No Compression|67.01 ± 5.34 (182/300)|76.00 ± 2.65 (300/300)|80.28 ± 3.63 (265/300)|
|Discard-All|72.25 ± 8.29 (247/300)|63.67 ± 3.06 (300/300)|80.45 ± 5.61 (220/300)|
|Sliding Window|71.16 ± 6.02 (188/300)|73.67 ± 1.53 (300/300)|88.01 ± 0.32 (250/300)|
|Summarization|70.60 ± 1.51 (238/300)|80.35 ± 1.39 (295/300)|89.18 ± 1.21 (239/300)|
|VERA|74.30 ± 3.02 (218/300)|89.40 ± 3.41 (263/300)|84.71 ± 3.93 (223/300)|

所有方法共同可评子集：同一列比较使用相同题目×repeat；仍是可用性筛选的条件子集，不能替代全benchmark。

|方法|Gemini＋Hermes（N=88）|DeepSeek＋Hermes（N=261）|DeepSeek＋DSH（N=173）|
|---|---:|---:|---:|
|No Compression|84.49 ± 7.39|82.02 ± 1.23|87.24 ± 2.64|
|Discard-All|87.70 ± 8.49|72.12 ± 4.56|85.11 ± 4.13|
|Sliding Window|82.96 ± 3.18|82.37 ± 0.51|88.48 ± 0.99|
|Summarization|82.85 ± 6.16|84.74 ± 3.09|91.51 ± 2.60|
|VERA|87.34 ± 2.89|89.70 ± 3.74|87.95 ± 2.24|

BC结论：DeepSeek＋Hermes的可评配对子集支持VERA优于No Compression、Sliding Window与Discard-All；对Summarization未达到校正后p<0.05。DeepSeek＋DSH未显示一致准确率优势；不显著不能当成等效证明。

## 2. MMBC：DeepSeek＋Hermes六策略

|方法|全部可评 mean±std (%)|有效/300|六方法共同子集 mean±std (%)，N=31|
|---|---:|---:|---:|
|No Compression|80.21 ± 4.77|88/300|84.76 ± 5.77|
|Discard-All|45.17 ± 6.36|111/300|66.19 ± 7.87|
|Sliding Window|79.29 ± 6.88|111/300|79.05 ± 7.19|
|Summarization|81.60 ± 8.75|87/300|83.81 ± 14.66|
|VERA|80.70 ± 1.99|126/300|86.19 ± 6.44|
|Vanilla视觉（不含视觉证据）|74.24 ± 3.47|129/300|81.43 ± 3.78|

**共同31题次上VERA点估计最高，但不能写成稳定或显著优于所有策略。** 该交集各repeat只有14/10/7题次；在另一种更严格的完整三repeat配对题簇上，VERA−vanilla为−12.12pp（11题簇，95%CI [−30.30, 0.00]，Holm p=1.0），方向会随可用子集变化。当前不足以确立核心MMBC优势。

## 3. 配对显著性与方差

配对使用两方法三个repeat均有效的题簇；10000次题簇bootstrap及sign-flip，比较族内Holm校正。下面的CI不消除可用性筛选偏差。

|实验|VERA−对照|完整题簇|差值pp [95%CI]|Holm p|
|---|---|---:|---|---:|
|BC / hermes|No Compression|80|7.08 [2.50, 12.08]|0.0112|
|BC / dsh|No Compression|58|0.00 [-3.45, 3.45]|1.0000|
|BC / hermes|Summarization|79|3.80 [0.00, 7.59]|0.0774|
|BC / dsh|Summarization|55|-1.82 [-6.67, 3.03]|1.0000|
|BC / hermes|Sliding Window|80|8.33 [3.33, 13.75]|0.0081|
|BC / dsh|Sliding Window|55|0.00 [-3.64, 3.64]|1.0000|
|BC / hermes|Discard-All|80|16.67 [10.42, 22.92]|0.0004|
|BC / dsh|Discard-All|56|0.60 [-2.98, 4.17]|1.0000|

MMBC各比较校正后p均为1.0，统计功效不足。Gemini BC配对也未达到显著。完整逐比较结果见[当前准确率明细](accuracy-current.md)，各方法条件mean的[题簇bootstrap95% CI](method-bootstrap95.json)。

## 4. RQ3：新七页协议分辨率实验

此表仅合并V10/V11/V12的新协议结果，未用更早分辨率实验填空；三代不当作新seed。

|历史页缩放|有效/300|mean±std (%)|
|---:|---:|---:|
|0.0|273/300|78.40 ± 1.39|
|0.25|222/300|79.33 ± 3.71|
|0.5|138/300|89.78 ± 5.41|
|0.7|98/300|90.62 ± 3.93|
|0.75|85/300|92.80 ± 1.31|
|0.8|56/300|90.79 ± 3.87|
|1.0|111/300|75.04 ± 7.24|

七档共同可评交集只有2题次，且其中一个repeat无观测；无法报告可信的七档同题avg3比较。1.0与0/0.25的完整三repeat配对仅5/3题簇，校正后p=1.0；其他配对没有完整题簇。**不能据这张条件表声称0.75最佳或非单调趋势已获统计支持。Finding 3应改为探索性观察。**

## 5. 真实成本、缓存与延迟

以下成本来自11月12日冻结的同题且用量完整子集，准确率口径与上面的最新表不同，不能拼接成一张最新Pareto图。Cached/non-cache/output/total均为每题次平均K tokens。价格沿用归档统一假设：cached $0.15/M、non-cache $1.50/M、output $9/M；是Gemini等价重估，不是DeepSeek或TokenHub实际账单，此次未重新核价。

|Harness|方法|共同N|Cached K|Non-cache K|Output K|Total K|等价$/题次|E2E秒|token cache hit%|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
|hermes|No Compression|134|780.65|105.41|16.21|902.27|0.421|363.42|88.10|
|hermes|Summarization|134|157.40|216.81|27.47|401.68|0.596|376.66|42.06|
|hermes|Sliding Window|134|278.36|109.85|14.45|402.66|0.337|315.52|71.70|
|hermes|Discard-All|134|246.92|101.93|26.10|374.95|0.425|440.82|70.78|
|hermes|VERA|134|109.33|49.49|10.68|169.51|0.187|325.59|68.84|
|dsh|No Compression|119|266.70|52.35|8.81|327.86|0.198|545.46|83.59|
|dsh|Summarization|119|133.39|88.21|12.02|233.62|0.260|521.79|60.19|
|dsh|Sliding Window|119|165.82|62.29|8.83|236.93|0.198|539.52|72.69|
|dsh|Discard-All|119|144.95|48.50|9.83|203.28|0.183|573.80|74.93|
|dsh|VERA|119|97.34|35.08|6.89|139.31|0.129|437.67|73.51|

在这些成本共同子集上，相比No Compression：Hermes VERA总token少81.2%、等价费用少55.6%；DSH VERA总token少57.5%、等价费用少34.8%。这能支持成本/表示效率的有条件结论。**缓存命中率本身并非处处更高**；VERA可通过降低绝对输入量节省费用。

历史API和渲染时间覆盖不足，不能把CLI/E2E当provider API latency，也不能用E2E减API补出渲染时间。Hermes视觉渲染已记录35题次、平均18.44秒；DSH视觉119题次、平均3.28秒，覆盖与计量协议不同，不能直接作跨harness渲染性能排名。工具缓存与模型token缓存分开。

完整[方法×benchmark成本大表](../2026-11-12/historical_cost_pareto.md)、[DeepSeek同题成本表](../2026-11-12/deepseek_paired_cost.md)、[文本Pareto图](../2026-11-12/pareto_text.png)、[多模态Pareto图](../2026-11-12/pareto_multimodal.png)。旧DeepSeek MMBC成本交集仅4题次，不能支持MMBC总体成本排名。

## 6. 受控baseline：文本压缩＋原生图像

仍无充分预算匹配的正式结果。可用三臂共同且预算匹配组：

|版本|benchmark|配对组数|VERA正确|Summary＋Native正确|Window＋Native正确|
|---|---|---:|---:|---:|---:|
|旧v4|BC-v3|3|3/3|3/3|3/3|
|旧v4|MMBC|1|1/1|1/1|1/1|
|bounded|BC-v3|1|1/1|1/1|1/1|
|bounded|MMBC|0|NA|NA|NA|

V8/V9正式运行没有新的有效配对：4条completed均为校准，不能当正式accuracy。不能声称已经证明VERA优于文本摘要/窗口＋原生图，也不能据当前数据证明其cache/non-cache显著低于受控baseline。[逐臂结果及控制缺口](../2026-11-12/controlled-information-loss.md)。

## 7. 信息损失量化

9个holdout；q004开发题不混入。

|表示|有QA条件/9|Probe QA正确/有效事实|比例|有效视觉重建语义评分|
|---|---:|---:|---:|---|
|原文本|9/9|31/32|96.9%|文本重建有记录|
|Summarization|9/9|7/32|21.9%|摘要重建有记录|
|Canvas 1.0|3/9|7/10|70.0%|无可评结果|
|Canvas 0.75|1/9|4/6|66.7%|无可评结果|
|Canvas 0.5|7/9|4/26|15.4%|无可评结果|

各方法覆盖条件不同，上表不是公平总体排名。五臂共同可评仅1道holdout、6个事实：原文本6/6、1.0x 6/6、0.75x 4/6、0.5x 2/6、摘要1/6。这可作为个例，不能写成总体重建成功或平滑时间衰减已验证。视觉重建0/0表示NA，不是0%召回。[完整信息损失报告与曲线](../2026-11-12/controlled-information-loss.md)。

## 8. 原Table 1异常排序与失败分析

已分析14920条历史Gemini轨迹并整理20个失败case。BC No Compression在31–60轮桶为94.1%（85条已评），101+轮为31.7%（208条已评）；其他方法也随长轨迹退化，这是描述性关联，不能归因为context rot的因果证据。没有找到明确context-limit日志，不代表没有发生。[失败分析](../../experiment5/experiment5.md)。

原Table 1候选的BC 59.8%可重建，但其244题次中No Compression有41条缺档被旧计算补0，且cohort按四个压缩方法成功筛选。整体69.0%尚未复现。因此不宜直接沿用旧排序解释。[Table 1来源审计](../../paper-table1/audit.md)。

## 9. 历史全部benchmark、消融和其他模型

[58个原始运行组的repeat均值、std和分母](historical-repeat-stats.md)包括BC/BC-ZH/XBench/Seal-0、BC-v3/MMBC、Qwen分辨率、AgenticDataBench、text-only及debug/不同预算版本；不同run不合并。部分多模态导出仅一个repeat，std必须为NA。它们不是已确认映射到论文Table 1/2的完整重建。AgenticDataBench按要求未补测。

Cache-aware VERA和AST/GUI没有独立完成的新实验，不列作完成结果。

## 可用于rebuttal的表述范围

- 成本/缓存：报告同题且usage完整子集的绝对token和等价成本下降，并给出覆盖率。
- 泛化：报告两harness的完整方法表、条件分母及配对统计；避免声称所有harness都提高准确率。
- MMBC：只能报告初步共同子集点估计，尚不能确立稳定/显著优势。
- RQ3：将Finding 3降为探索性观察，不声称目前证实非单调规律。
- 受控baseline和信息损失：必须保留未完成/覆盖不足，不将校准或个例当正式实验。

可直接使用的成本描述（需保留限定语）：

> On matched BC subsets with complete usage records (134 Hermes and 119 DSH question–repeat instances), visual rendering reduces total token usage by 81.2% and 57.5%, respectively, relative to No Compression. Under the same cache-aware pricing assumption, the corresponding equivalent costs decrease by 55.6% and 34.8%. These are conditional comparisons on observed subsets, rather than full-benchmark cost estimates.

[当前统计与来源SHA](results.json) · [所有准确率和配对明细](accuracy-current.md) · [历史运行组索引](historical-repeat-stats.json)。

## BC超时子集与探索性推算（新增）

[逐策略难度比较、推算公式及敏感性分析](bc-timeout-transfer.md)：不能确认固定比例关系；DeepSeek＋Hermes约82.20%、DeepSeek＋DSH约82.14–82.47%仅为全300题次的探索性估算，**不是实测accuracy，不替代主表或mean±std**。

## 最新运行与缺口审计

[完整300题覆盖、RQ3评分连接失败恢复、MMBC历史缺终态追溯及剩余额度](recovery-audit.md)。此页区分历史失败、新队列运行、待判分和预算耗尽；新补跑尚不代表完整avg3。

[第一批RQ3旧判分恢复后的mean±std及有效样本数](rq3-grading-recovery-snapshot.md)（不含本轮新预测，非完整300题）。
