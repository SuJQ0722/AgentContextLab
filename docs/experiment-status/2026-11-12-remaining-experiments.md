# 停跑后的实验缺口与优先级（2026-11-12）

> 图像预算后续已更新为 [history≤5 / recent≤2](../visual-integrity/history5-recent2-2026-11-12.md)，下列完成量仍为停跑时历史统计。

状态快照：2026-11-12 02:43:03 UTC。此前15台本轮CCI在02:32:55 UTC确认SUSPENDED/ready=0，其余90台旧实例也暂停。本次文档及代码修改没有启动实验。下列数字是停跑统计，不是新五图协议的完成量。完整本机报告位于 `/mnt/data/acl-results-20261112/REPORT.md`。

## 剩余工作

|优先级|实验|已有结果|仍缺什么|
|---|---|---|---|
|P0|MMBC DeepSeek+Hermes，VERA/vanilla及四种管理方法，100×3|VERA有效84/300、vanilla101/300；none81、summary82、window104、discard109|大量系统/未知超时、未终态与少量未评分；各臂分母不同。目前不能支持VERA优于所有方法；五图版属于新协议，需要单独冻结与标注|
|P0|BC多model/harness，100×3|DeepSeek Hermes none300、window300、discard299、summary289、visual236有效；DSH none258、window245、discard213、summary234、visual223有效|分类未知timeout与缺失；少量现成答案未评分；若后续补跑须保留旧attempt，不能把条件结果包装为完整300。历史Gemini不重跑，400题次缺档继续标未知|
|P1|受控baseline：summary/window+native images 对比视觉表示|旧bounded三臂共同有效且预算匹配：BC v3仅1组，MMBC0组；尚未覆盖原计划三个多模态benchmark|V8正式visual槽14条系统超时；V9文本47槽中16 blocked、31未启动；共享control target未发布。先修控制依赖和预算匹配，原生图必须一致；五图视觉恢复不能自动成为有效受控实验|
|P1|真实成本、缓存、延迟|已有历史大表、DeepSeek同题表、文本/多模态Pareto；BC Hermes共同完整成本134题次，DSH119，MMBC仅4|补齐可恢复usage；明确已知费用下界、失败重试费用、缓存token口径。provider内部API时间缺失不能由HTTP或CLI代替；MMBC Pareto当前不能支持总体排名|
|P1|RQ3：0/.25/.5/.7/.75/.8/1，100×3|有效题次依次293/250/222/195/204/211/236；已计算条件mean±std、题簇bootstrap与配对检验|均非完整300；未知timeout/未评分仍存在。所有比较经校正未显示显著差异，不能据条件均值宣称非单调规律。五图会改变证据保留，若采用应统一为新的分辨率协议|
|P1|信息损失：重建+Probe QA|V10共50槽：26 completed、12 timeout、12无终态；9个holdout的五臂共同QA仅1题6事实|视觉三分辨率无有效重建语义评分；completed不等于成功重建，length终止单列。先解决重建输出完整性与judge链路，不能把缺失填0或宣称平滑衰减|
|P2|反直觉排序/失败case分析|已做系统超时与传输诊断|仍需核对全部No Compression失败类型、按长度分桶，以及XBench/Seal失败案例分析的覆盖情况；不把传输诊断冒充完整实验5|
|不再新增|avg4、AgenticDataBench、Gemini重跑|按用户决定跳过|保留历史结果；均不列入自动补跑队列|

有效数包含明确预算耗尽记0的题次；它不是“无错执行次数”。系统错误有证据才排除；未知超时、未评分、缺档单列。mean±std为3个repeat准确率的均值±样本标准差，分母不齐时明确条件结果。重试不增加seed；费用不能随系统排除而删除。

## 下一轮应先解决的依赖

1. 审查五图实际请求的保留证据、近期分页和大小；当前只有离线回归验证，没有新模型验证。
2. 冻结新协议与输出目录，保留历史全部成功/失败记录；不得依据正确答案选择attempt。
3. 优先恢复MMBC核心比较与BC两harness，再处理受控target依赖、信息损失judge、RQ3缺口。现阶段不启动，不给未经验证的完工时间。
4. 现有成本表/统计可继续离线整理；新的付费评分或补跑需后续明确恢复指令。

五图实现与局限见[视觉记忆设计审计](../visual-integrity/visual-memory-budget-2026-11-12.md)。新上限减少发送内容，但尚未修复300秒请求截止、全历史重渲染或长期检索，因此不能称作超时问题已解决。
