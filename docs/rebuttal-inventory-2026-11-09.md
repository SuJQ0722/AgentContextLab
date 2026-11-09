# Rebuttal 规划与实际证据盘点

审计日期：2026-11-09。依据仓库历史报告、机器可读 status、manifest 和真实轨迹 journal。此文件列的是证据是否足够，不以脚本存在、平台 Running 或模型会读图代替实验完成。

| 原规划 | 已有产物/有效范围 | 状态与缺口 |
|---|---|---|
| 所有方法×benchmark cached/non-cache/output/total/$/latency/acc | 历史报告中五方法共同已评分交集：BrowseComp 每方法164条/95题；BC-zh689/265；SEAL-0302/108；SEAL64k223/93；XBench275/96；BC-v3238/238；MMBrowseComp322/322。文本与多模态 Pareto 均已输出。 | **历史重建完成但非所有历史完整 cohort**。API 完整日志只覆盖部分，renderer 时间缺失；AgenticDataBench 缺 token 计量不能补造。美元为官方价格假设下重估。新 DeepSeek 汇总待有效版本+评分。 |
| 两模型×两 harness 的可迁移性 | 历史 Gemini/Hermes；新 DeepSeek/Hermes+DSH 的 BC100×3×五策略真实执行。 | **部分完成**。新版本全量评分尚未收束；没有完成的新 DeepSeek 多模态 benchmark 泛化大表。工具图像 fixture 和 BC 文本 canvas 不等价。 |
| 原生图像保留的摘要/窗口 baseline | v5明确授权的单例第三attempt完成，六臂pilot通过实际token/原生图gate；固定180臂队列已扩展运行，目标16。 | **部分运行**。07:39 UTC六个pilot完成，51臂因17个prefix资格阻断未跑：15个无原生图、2个未达阈值。不是51条有效比较；不替换题目。完整三benchmark与全轨迹公平对照仍缺。 |
| 主表 avg@4、均值/std、bootstrap、paired test | 历史文本 avg@3 离线恢复与配对统计已做；用户后续要求无需新文本推理。 | **缩减后的文本统计完成**，不声称原 avg@4 范围完成。论文 Table1 整表映射、缺失处理仍有来源问题；不能用19题所有方法成功交集替代原全集。 |
| Table5/RQ3 100题×3×多分辨率 | 最终0/.25/.5/.7/.75/.8/1七档2100项，六档复用修复版，新.75独立300项；.125退出比较但保留费用。 | **实际运行中，未完成**。07:47 UTC五档各16活跃，另两台仍Pending；已启动最终来源固定报告与分scope评分。见[七档部署](rq3/final-seven-cloud.md)。旧renderer/wire缺图样本不能复用。 |
| No Compression 失败原因、轨迹长度分桶、VERA弱项案例 | 14,920历史轨迹；20个 XBench/SEAL VERA 错例的离线分析与报告。 | **离线分析完成**，不把没有截断/API 证据的答错强行归因。 |
| canvas 重建+probe，摘要/文本对照，1/.75/.5与距离 | 单轨迹 pilot：3片段相关、不等于3独立题；旧phase2：7独立题、34条件记录、106请求、37 missing usage，无完整三分辨率视觉 QA cohort。新phase3：10独立题、完整实际画布、五条件。 | **旧结果仅方法/失败 pilot，新phase3质量停派**。41次请求均已返回；视觉QA无有效配对，多个reasoning耗尽，另有明确不可读拒答，尚不能提交完整信息损失曲线。严格语义事实评分与字符串覆盖分开。年龄为历史原位置，不能证明因果衰减。新阶段最多190调用，不承诺10题全部有有效响应。 |
| cache-aware VERA冻结画布/离散降档 | 缓存计量和 renderer 审计存在。 | **方法增强未跑**；计量存在不是该算法的实验结果。 |
| AST/GUI补图或新场景 | 未发现完成的独立数据集评估。 | **未跑**，不得作为已证实领域泛化。 |

新 phase3 固定问题：q004、q009、q017、q019、q020、q021、q022、q023、q025、q026。按 BC 问题顺序、repeat1、首次真实共享策略压缩和来源可核查性选择，不看答案正确性。它排除了 renderer 输入中含原生图片的历史；因此明确只评估**文本历史视觉压缩**的信息损失。每题全部 renderer 输入用于原文 control、全部画布用于视觉条件；早/中/晚位置仅用于事实抽样，不裁剪评估画布。

来源：

- `docs/experiment1/experiment1.md` 与 CSV/Pareto 图。
- `docs/paper-table1/audit.md`、`docs/rq3/provenance-audit.md`。
- `docs/experiment5/experiment5.md`。
- `outputs/experiment3/controlled-native-v2/status.json`：旧 gate 未通过。
- `outputs/campaigns/rq3-deepseek-bc100-r3/status.json`：旧暂停快照，不是新 RQ3 队列。
- `outputs/experiment6/full-canvas-phase2/{manifest,results,usage-summary}.json`：旧真实失败完整保留。
- `outputs/experiment6/shared-full-canvas-phase3/{manifest,status,results,usage-summary}.json`：新来源冻结与增量结果。
- `outputs/campaigns/bc100-r3-hermes-parity-v3/monitor/status.json`：主队列执行计数；重试/评分在各自新队列记录。

“completed”只表示执行终态；“effective sample”须同时满足来源、图像送达、计量、输出/评分要求。用户授权的新重试保留原费用/失败，不把它们当独立重复样本。
