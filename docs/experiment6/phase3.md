# 实验6 phase3：真实完整画布的信息损失

2026-11-09 新启动的独立补充实验，代码 `scripts/info_loss_phase3.py`，输出 `outputs/experiment6/shared-full-canvas-phase3/`。原 phase2、无效初版 scale pilot 以及所有失败/费用保留，未覆盖历史结果或改动核心实验运行文件。

**范围：10个不同 BC 问题、五条件、单并发、最多190次请求。** 模型固定 `deepseek-v4.1-flash-1017/zijian/sfb`，不调用 Gemini；8192 max output/reasoning tokens。最多每题3次事实生成+1次摘要+五条件各重建/QA/语义评分=19次。没有输出的重建不会再调用 judge。每个请求唯一标记并可恢复，未知或失败请求不自动重试。连续3个基础设施错误暂停新增请求；未知计量不补0。核心优先，进程空间拥挤时等待。

## 来源和条件

固定顺序选择 q004、q009、q017、q019、q020、q021、q022、q023、q025、q026 的 repeat1 首次实际压缩。源为新共享策略的真实 `_full_history`，与 `messages_rendered`、font16、history scale1、renderer版本、图像ledger逐项核对。实际输出 dataURL 解码后的 SHA、尺寸与 native attachment 一致，共26张原始完整画布。完整来源、消息、原图和衍生图全部冻结，manifest SHA：`0d0bfac679ccb04966ced7399bb6810b8f761e906a7acc7eacff0aa5afca2376`。

五条件为：完整原始文本、全部原始1x画布、全部画布线性尺寸0.75x、全部画布0.5x、同一完整文本生成的摘要（请求最多600词，实际长度需从输出核实）。降采样为确定性 Lanczos，无裁切、无换成简化片段，保留所有页面；这不是历史策略只降低远期部分的 `history_scale` 消融，也没有匹配五条件 token budget。

源历史本身含原生图片的 case 不在此队列。该实验验证**文本历史被视觉压缩后的信息保持**，不能称为新的多模态 benchmark 泛化；完整文本 control 也不是有表格丢失缺陷的旧 Text-only Rendering ablation。

## 事实、评分和距离

每题从完整源历史最早/中间/最后的工具结果分别抽最多2个 number/date、URL、entity 事实。原文 quote 必须逐字存在、答案必须在 quote 中、题目不能泄漏答案；问题应指明具体来源/实体以避免“乘客/所有人”歧义。所有条件使用同一组问题。重建调用只见条件内容，不见原文答案或评分事实；QA 只见问题，不见参考答案。

- QA 采用短答案规范化后的严格 exact match；缺输出/无效 JSON 单列，不默认为答错。
- `reconstruction_answer_substring_coverage` 仅为答案字符串覆盖，短数字可能误匹配，**不是 semantic key-fact recall**。
- 独立语义评分调用检查实体、关系、数值、极性，并要求支持证据原样出现在重建文本中；same-model judge 仍有偏差，需要人工抽查，不能当无偏真值。
- 报告同时给每条件观察分母、共同事实分母、缺失导致的准确率上下界、五条件完整配对题数。每题最多6个事实，不把事实当60个独立题目。
- 距离是事实原位置之后的工具轮次；早中晚有内容差异混杂。结果只支持观察性关系，不能证明因果时间衰减。
- 输出8192预算可能耗在 reasoning 或截断，全部保留 finish_reason，不能把重建不完整都解释为画布信息不存在。

## 计量和运行

每次请求保存 purpose、原始 usage、HTTP状态、实际返回model、finish_reason、图像SHA/尺寸/detail、请求字节数、客户端 HTTP耗时、错误。缓存字段缺失保持 unknown；provider内部延迟、图像token单独计数及实际美元成本若缺失则为空，不拿本地估算补齐。source生成的既有核心费用不重复算作本实验新增支出。

`running.json` 提供 PID；`status.json` 提供 `status/case_count/conditions/calls_started/calls_returned/missing_usage/concurrency/max_requests`；每个条件更新 `results.json` 与 `report.md`，每次调用更新 `usage-summary.json`。报告正文在事实逐题产生时标明当前共同分母，不假定已有60个有效事实。无请求完成前不报告信息损失结论。

离线验证：`python -m unittest discover -s tests -p 'test_info_loss_phase3.py' -v`，5项通过，覆盖完整源/全部图保留、尺度变化、来源不匹配拒绝、答案泄漏拒绝、语义评分证据验证、共同分母及缺失区间。实际 q004 原画布已用图像工具查看，非空且有真实工具文本/URL；这只验证可见性，不宣称语义无损。

只读绘图器 `scripts/report_info_loss_phase3.py --watch` 每60秒检查增量结果，出现真实观测后生成 `analysis/resolution-age.png`、PDF、事实类型/原距离明细与 Markdown；study completed/hold 后最后更新并退出。没有观测时不画虚构曲线。缺失分母与相关事实限制标在图及表中。

逐调用实时统计读取独立只读 observer 的 `live-status.json`（最多60秒刷新，含 observed_at、worker_alive、calls_started/returned、in_flight_or_unknown、完整usage覆盖）；执行器 `status.json` 在每个条件结束更新，不应据其旧计数断言没有调用。observer不修改模型请求或执行状态。

实际请求保留原 journal 的每页 `detail`，不擅自提升到 high。例如 q004 的3页为 low/low/high，1x请求8,499,266字节，尺寸1019×6115、1015×1523、1016×5213。三个尺度保持对应页面 detail 不变；provider仍可能自行缩放，故该实验不能独立测出纯像素分辨率的效应或provider内部图像token规律。

## 2026-11-09 上传故障后的显式恢复

原直连部署在第26次请求后按预定“三次连续基础设施失败”暂停，最后三次都是90秒 `WriteTimeout`，不是 AFS 故障。此前共26次 started/26次 response，5次上传失败的 usage 未知。请求未知费用保留，未重发已有26次。

新增独立运维入口 `scripts/info_loss_phase3_ops.py --deployment proxy1-20261109`，只对尚未请求的条件使用已有内部代理；旧科学脚本及 manifest/hash 保持原样，完整图片字节、detail、model、输出预算、读写超时、prompt 不变。`operations/proxy1-20261109/deployment.json` 保存26次旧调用证据哈希、运维代码SHA、代理主机（不保存凭据）和明确迁移范围；每个新 HTTP 请求另存 bodySHA、字节数、客户端耗时、状态。既有 call ledger 继续负责禁止重复调用，旧 transport_error 仍是缺失观测，不能在新路径成功后补写为成功。

无模型的直连/代理 HEAD 连通检查都返回404，说明端点可达，但不能证明大图上传成功；是否修复依赖下一个计划内完整画布请求的实际响应。不同传输部署的耗时不得当作同一网络条件比较。再次连续3个基础设施错误仍暂停，不自动重试失败条件。
