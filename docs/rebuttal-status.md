# Rebuttal 实验状态（2026-11-09）

本页替换已过期的 11 月 8 日启动前状态。SCO 凭据与云资源已就绪，云端和本机核心实验已经实际运行；不能再将它们描述成“等待凭据”。执行结束不等于答对，传输验证不等于多模态 benchmark 完成。

| 项目 | 当前可核实状态 | 仍缺的证据 |
|---|---|---|
| 实验 1：成本、缓存、延迟 | 历史 Gemini 日志重建已完成，已有方法×benchmark Markdown 大表及文本/多模态 Pareto 图；没有新增 Gemini 调用。[报告](experiment1/experiment1.md) | 历史渲染耗时缺失，API 耗时覆盖不全；美元值为标明价格假设的重估，非 TokenHub 实付。新 DeepSeek 全队列评分/有效版本汇总仍在推进。 |
| 核心跨 harness 实验 | BC-100×3×5 策略×2 harnesses，固定 3,000 项。共享 Hermes 策略与图像传输修复版已大量实际执行；按明确授权的新 retry1 队列处理 963 项，保留旧失败和费用；主控已提交 10 个云 cell，每 cell 目标16，本机 canary 有真实 HTTP 成功。 | 当前是文本 BC 的跨 harness 实验；重试选择、路由、版本与基础设施失败必须分层，不能把重复 attempt 当新增题目。准确率需等待评分；实际并发看实时 monitor，不以提交目标代替。 |
| 新多模态 benchmark 泛化 | 有历史 Gemini 多模态日志、真实工具/图像传输验收和少量受控 prefix 调试；**尚没有完成、可直接报告的新 DeepSeek 全量多模态泛化结果**。 | BC-v3、MMBrowseComp、AgenticDataBench 的完整新版本、配对多方法评测仍缺；BC 的文本渲染成图不等于多模态输入 benchmark。 |
| 实验 3：摘要/窗口 + 原生图像 | 旧校准和 v2/v3 continuation pilot 未通过正式预算/图像 gate，未产出有效完整比较。新 v4 独立实现已通过 localhost 真工具循环验收，正在准备两题配对 pilot；固定扩展范围为 180 臂、最多4并发。[旧失败证据](experiment3/README.md) | 需两题三方法原生图一致、真实 token 匹配 gate、后续工具调用和终态评分通过，再扩固定队列。180 臂是两个 benchmark 的小队列，不是原计划三个 benchmark 全量。 |
| 实验 4：显著性/方差 | 历史文本 avg@3 离线统计与配对分析已做，无需新 Gemini；[Table 1 来源审计](paper-table1/audit.md)。 | 用户已缩减范围，不补泛化 avg@4。提交论文 Table 1 全体来源仍未完全对应，不能将成功交集或缺失补零当无偏全表统计。新核心/RQ3 须按 question 聚类、同题同 repeat 配对。 |
| RQ3：分辨率 | 旧 DeepSeek 七档队列曾有 170 个新任务终态，但因旧图像送达错误暂停；历史 Table 5 来源审计已保存。[来源审计](rq3/provenance-audit.md) | 旧计数不是有效七档 100×3 结果。新的修复版和评分由独立队列推进；须单独冻结新来源，不能直接把旧无图压缩结果混入。 |
| 实验 5：失败原因和轨迹长度 | 已从 14,920 条历史轨迹离线分析，并检查20个 VERA 失败 case，无新增模型调用。[报告](experiment5/experiment5.md) | 结论受历史 instrumentation 覆盖限制；缺少证据的失败不能硬分成 context 截断。新版本可另做补充，不替换历史分析。 |
| 实验 6：信息损失 | 旧单轨迹 pilot 和七题 phase2 已结束，但无完整跨分辨率视觉 QA 配对 cohort。新 phase3 冻结10个不同问题的真实完整 renderer 输入/画布，已启动单并发、最多190次 DeepSeek 请求。[新协议](experiment6/phase3.md) | 新结果尚在生成。比较完整原文、摘要、完整画布1/.75/.5；事实覆盖、语义重建与 QA 分开。距离仅观察关联，不声称因果时间衰减。 |
| 可选 cache-aware VERA | 未执行冻结 canvas/离散分辨率的独立效果实验。 | 不能以已实现缓存记录代替 cache-aware 方法比较。 |
| 代码 AST / GUI 展示 | 没有完整新数据集实验。 | 作为额外展示可另行明确数据集与公平对照；当前补充实验不包含它。 |

## 当前统计边界

原核心 monitor 的一个可复查快照（2026-11-09 04:37:58 UTC）记录 2,996 个 attempts：completed 2,037、timeout 572、failed 368、not_started 6、unfinished 13。这是旧主队列该时刻的执行状态，不是正确数，也不包含随后 retry1 的最终进展。最新状态以 `outputs/campaigns/` 对应版本的 `monitor/status.json`、retry manifest、judge 状态为准。

原实验3 v2 状态为 `blocked: pilot_realized_budget_or_native_gate_failed`；原 RQ3 的 `status.json` 时间停留在 11 月 7 日。这些旧状态必须保留作历史证据，不能当成新队列实时状态。主代理统一维护新队列启动/停止和评分，子任务不修改冻结核心文件。

缓存、non-cache、output 使用 raw provider usage；缺字段为 unknown，不能使用 SDK 默认0补齐。API 客户端耗时、provider 内部延迟、渲染耗时、端到端时间分别记账。没有适用路由价目时，不报“实付美元”。模型缓存与 Serper/Jina 工具缓存分别统计。所有失败、预热、校准、重试费用保留。

## 必须保留的负面与来源证据

- 匹配 BC-EN 59.8% 的旧候选 cohort 经过四个压缩方法成功筛选，并将41条缺失 No Compression 记录补零；审计复现该计算，但不认可缺失=答错。总体69.0%来源尚未完全匹配。
- 旧 RQ3 绘图有 +0.9 个百分点平移，并将0.125标作0.1；原始未平移点和来源独立保存，不能由聚合点虚构 CI。
- 旧 Text-only Rendering 表格路径会丢单元格；新完整原文 control 不冒称复现了该历史 ablation。
- 旧 Hermes 压缩图像被错误转为 caption 的轨迹保留，[wire 审计](vision-routing-audit.md)明确区分实际有压缩、无压缩、未观测范围。修复版验收不使旧失败自动有效。
- 七题信息损失 phase2 的106次请求中37次 usage 缺失。其字符串命中率不是 semantic key-fact recall，视觉 QA 缺失不能当成零准确率或拿不同分母比较。

详细盘点与有效样本定义见[完整审计](rebuttal-inventory-2026-11-09.md)。
