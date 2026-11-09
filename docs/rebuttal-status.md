# Rebuttal 实验状态（2026-11-09）

本页替换已过期的 11 月 8 日启动前状态。SCO 凭据与云资源已就绪，云端和本机核心实验已经实际运行；不能再将它们描述成“等待凭据”。执行结束不等于答对，传输验证不等于多模态 benchmark 完成。

| 项目 | 当前可核实状态 | 仍缺的证据 |
|---|---|---|
| 实验 1：成本、缓存、延迟 | 历史 Gemini 日志重建已完成，已有方法×benchmark Markdown 大表及文本/多模态 Pareto 图；没有新增 Gemini 调用。[报告](experiment1/experiment1.md) | 历史渲染耗时缺失，API 耗时覆盖不全；美元值为标明价格假设的重估，非 TokenHub 实付。新 DeepSeek 全队列评分/有效版本汇总仍在推进。 |
| 核心跨 harness 实验 | BC-100×3×5 策略×2 harnesses，固定 3,000 项。共享 Hermes 策略与图像传输修复版已大量实际执行；按明确授权的新 retry1 队列处理 963 项，保留旧失败和费用；10 个云 cell 已实跑并持续补位，每 cell 目标16；11月9日已将剩余Huoshan路由从1提高到16，本机停止新增；新图像压缩后请求和真实回复均已验收。[恢复与统计协议](statistics/bc100-v3-avg3-and-retry.md)。 | 当前是文本 BC 的跨 harness 实验；重试选择、路由、版本与基础设施失败必须分层，不能把重复 attempt 当新增题目。核心评分4并发、RQ3独立评分1并发、受控独立评分1并发均已部署；核心与RQ3统计watch自动更新。完整100×3覆盖前不发布完整mean±std/paired p。实际并发看实时monitor，不以提交目标代替。 |
| 新多模态 benchmark 泛化 | 有历史 Gemini 多模态日志、真实工具/图像传输验收和少量受控 prefix 调试；**尚没有完成、可直接报告的新 DeepSeek 全量多模态泛化结果**。 | BC-v3、MMBrowseComp、AgenticDataBench 的完整新版本、配对多方法评测仍缺；BC 的文本渲染成图不等于多模态输入 benchmark。 |
| 实验 3：摘要/窗口 + 原生图像 | v5单例第三attempt完成并评分正确，六臂pilot实际token/原生图gate通过：BC-v3最大token差1.82%、MMBC0.72%。固定180臂扩展已运行，目标16，仍记录cache/non-cache/output及未知用量。[协议](experiment3/controlled-v4.md)。 | 07:39 UTC终态57中只有6个pilot completed，另51臂因prefix不合格未运行：15个MMBC prefix原题没有原生图（45臂），2个BC prefix未达16384阈值（6臂）。保留固定cohort，不换题、不放宽gate。两benchmark小队列不等于原计划三个benchmark全量。 |
| 实验 4：显著性/方差 | 历史文本 avg@3 离线统计与配对分析已做，无需新 Gemini；[Table 1 来源审计](paper-table1/audit.md)。 | 用户已缩减范围，不补泛化 avg@4。提交论文 Table 1 全体来源仍未完全对应，不能将成功交集或缺失补零当无偏全表统计。新核心/RQ3 须按 question 聚类、同题同 repeat 配对。 |
| RQ3：分辨率 | 最终0/.25/.5/.7/.75/.8/1各100×3，共2100。0.7原云节点被关闭后，本机以16并发接续219待运行题；15已付费中断题独立固定恢复，与主队列共享16slots。0/.25/.5/.8云端继续运行，.75已迁回agents且worker Running，1.0仍等待可用容量。[恢复说明](recovery-2026-11-09.md)。 | 新最终报告`rq3-final-seven-v2`固定替换15观测并累计费用；不增加repeat。完整覆盖前不发布完整avg3±std/显著性结论。 |
| 实验 5：失败原因和轨迹长度 | 已从 14,920 条历史轨迹离线分析，并检查20个 VERA 失败 case，无新增模型调用。[报告](experiment5/experiment5.md) | 结论受历史 instrumentation 覆盖限制；缺少证据的失败不能硬分成 context 截断。新版本可另做补充，不替换历史分析。 |
| 实验 6：信息损失 | 旧phase3质量停派证据保留。新phase4禁thinking已真实验证；完整像素分块与统一有界事实重建已冻结。大图base64上传超时后，imgbb URL传输已通过真实下载byte/pixel一致性检查，1x真实视觉QA已4题答对3题，正在完成其余五臂质量验证。[恢复说明](recovery-2026-11-09.md)。 | 质量门通过才自动放行固定队列；旧7调用+URL阶段183共190上限，开发题q004与其余9题主分析分开。尚无完成的信息损失曲线。 |
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

## 2026-11-09 恢复后的实时入口

- 核心额外一次恢复：`outputs/campaigns/bc100-r3-hermes-parity-v3-retry1/monitor/status.json`；固定963条的`retry-ledger.json`，未选择的原completed保留。原始first-pass费用不能删除。
- 核心评分与avg@3：`outputs/grading/bc100-v3-deepseek-sfb-v1/status.json`、`analysis/summary.md`；RQ3独立目录见专页。
- RQ3当前派发：`outputs/supervision/rq3-final-seven-runtime.json`；最终统计`outputs/grading/rq3-final-seven-v2/summary.md`。原ops1与原0.7云控制器均只作历史证据。
- 受控baseline：`outputs/experiment3/controlled-native-v4/status.json`及ops3状态；六臂pilot已通过，固定180臂派发中，prefix资格阻断与实际完成分开。旧失败、校准和恢复费用保留，不自动第四次重跑。
- 信息损失：旧`shared-full-canvas-phase3/quality-hold.json`保留；新`outputs/experiment6/paired-repair-phase4-url1/`保存真实URL门与后续固定队列。

补充调度的共享文件锁维护只对取得blocking lock时的EAGAIN做有界等待；不会重试Popen、账本写入或模型请求。原核心只读观察器已在新监控接续后退役，原最终快照仍保留，以减少已冻结结果的重复AFS扫描。

新核心发现一条DSH compaction原始usage含相互矛盾的两组别名计数；原始record保留，对冲突prompt/output/non-cache记unknown。不能声称所有返回均有完整计量；见新monitor的conservation_issues和health-audit。

信息损失phase3曾在26次已请求后因连续上传超时暂停；独立proxy运维入口已恢复仅未来未请求项，原26次请求未重发。首个新完整图请求已HTTP200并有守恒usage，但输出预算耗尽而没有最终QA，仍按缺失记录，不视为视觉QA成功。

受控v5只修复transport恢复与诊断：localhost真实Hermes测试覆盖摘要断线、tool-call SSE断线后恢复、原生有限6次请求失败、actual预算越界硬停，未新增重试循环。获授权的单例第三attempt已完成并通过六臂门，固定180臂扩展队列已启动；不自动第四次重跑。其余核心队列不受此门影响。

信息损失质量停派记录：`outputs/experiment6/shared-full-canvas-phase3/quality-hold.json`。已观察到视觉QA的8192 reasoning耗尽而final为空；q017 1x重建另有完整最终回答，明确称图中文字低清而无法可靠还原。该拒答保留作可读性负面证据，不以HTTP200或像素传输验证代替有效重建，也不能断言只增加输出预算即可解决。

2026-11-09 05:55 UTC采样：核心retry1已有134 completed、135 timeout、43 failed，其余正在派发或待执行；10个云节点心跳新鲜。核心有效评分约1480（持续增长，含4个先导评分及1个固定补评），RQ3主队列21终态、约12活跃，另1个经证明确未启动的恢复已完成并评分。以上completed均不是正确数，最终以machine-readable状态和固定选择ledger为准。
