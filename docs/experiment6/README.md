# 实验 6：真实历史信息损失 pilot

单路 DeepSeek pilot 已完成，正式跨轨迹实验尚未完成。数据来自实际 BC q003 DSH 压缩前的三个 tool response 片段，每段固定取前 1600 字符，源顺序固定；源轨迹、事件序号、step、字符切片和 SHA256 保存在 `outputs/experiment6/real-trajectory-pilot-v2/manifest.json`。该轨迹最终超时，不能据此推断总体成功轨迹的损失分布。

每段比较原文文本 control、新生成 150 词摘要、同一 1x PDF 画布经 Pillow Lanczos 采样后的 1x / 0.75x / 0.5x。三组分辨率以同一原文、同一问题和同一参考事实配对。另有一次直接使用历史保存的四张完整 canvas 的重建和 probe，不以简单重渲染替代完整图。

模型由根 `configs/experiment.json` 读取，冻结为 `deepseek-v4.1-flash-1017/huoshan/huoshan`；只用 DeepSeek。并发 1，最多 60 次 API 请求，预计正常路径 54 次，每次输出上限 8192 tokens，HTTP 超时 180 秒。现有 BC campaign 不改动。

- 重建输入只含待评估表示和统一任务说明，无原文答案。
- Probe 输入只含待评估表示和问题，不含参考答案或 evidence quote。
- 事实从原文生成后，要求 quote 完整出现在源文本、答案完整出现在 quote、问题不直接包含答案。保存被验证事实。
- Exact probe score 要求短答案经空白/case 归一后完全相等；重建指标为答案子串覆盖率（answer-substring coverage），只检查答案字符串经casefold后是否出现在重建文本任意位置，不是语义 key-fact recall。二者与 VLM judge 分开。
- Judge 能看到原文和重建，返回逐事实保留判断和 faithfulness 分数。生成、回答和评判同模型，存在自评偏差。
- 每次调用保存请求 prompt / 图像 hash 与尺寸、raw response、provider usage、cached details、client HTTP time。没有供应商图像 token、处理时间或网关实付价格时保留未知；HTTP 时间不能叫 provider API latency。
- 调用前写 started marker。已有 response 复用；started 但无 response 视为结果未知，不自动重试付费请求。transport error 同样不静默重试。

三个片段来自同一轨迹，不是三个独立题目，不计算显著性。原 step 距离仅为描述性变量；切片移除了其他历史干扰，不能声称测到了随真实时间平滑衰减。该原文文本 control 不是历史 Text-only Rendering ablation，摘要也不是原日志的 native summary。此 pilot 未匹配摘要/图像 token budget。完整 canvas 重建可能超过输出上限，必须保留截断/超时状态。

## 运行与读取

```bash
# 准备，无 API 请求
python scripts/info_loss_eval.py
# 从已准备的 manifest 启动 / 恢复，单进程锁防重复
python scripts/info_loss_eval.py --live --resume
# 只读统计与图，无 API 请求
python scripts/info_loss_report.py
```

结果：`outputs/experiment6/real-trajectory-pilot-v2/results.json`、`report.md`、`usage-summary.json`、`pilot-curves.png/pdf`。运行中的统计仅覆盖已返回的请求，in-flight usage 未知。正式论文结论还需跨轨迹/benchmark 抽样，人工审核事实与 probe、控制上下文长度及轮数、引入独立 judge。

## 分辨率干预校验

首版准备错误地把 `history_scale` 用于单轮 renderer，默认 recent_rounds 使三个档位图像完全相同。发现后立即停止，保留 `outputs/experiment6/real-trajectory-pilot/invalid-resolution.json`。已完成的五次 fact/summary/原文 control 调用复用于 v2；一个已发出的图像重建请求结果未知，未自动重试，usage 仍未知。旧目录与新目录的这五条调用是同一调用，费用不能重复累计。

v2 固定同一 1x PDF 画布后确定性降采样。三个片段均验证尺寸为 1014×306、760×230、507×153，且 SHA256 不同。此干预是像素分辨率下降，不能称作历史 VERA 的整段 `history_scale` 策略复现。

## Pilot 最终状态

16个条件已终止并保存：15个片段表示条件，加1个原始四canvas完整条件。真实结果见 [report.md](report.md)，计数见 [usage-summary.json](usage-summary.json)。

| 片段方法 | 已返回 Probe QA | 未知的题数 |
|---|---:|---:|
| 原文 control | 16/18 | 0 |
| 新摘要 | 12/18 | 0 |
| 固定画布1x | 16/18 | 0 |
| 固定画布0.75x | 15/18 | 0 |
| 固定画布0.5x | 11/12 | 6 |

0.5x有一次请求传输超时，六题未知，不能把11/12与其他18题分母直接排名。1x第一片段重建也保留为interrupted_unknown。每个片段六题均来自同一条轨迹，不是18道独立benchmark问题。

**原始四canvas完整重建未得到最终内容**：300.18秒client HTTP，finish_reason=length；输出8192 tokens全部为reasoning，最终content为空。其后原始canvas Probe QA传输超时（180.18秒），18题结果未知；没有把完整图换成简单片段，没有重试。空重建的答案子串覆盖率记0仅说明本次预算内无输出，不能解释为模型完全看不懂图像。由于没有重建文本，不调用judge。

共52条调用记录，49条有usage，另3条usage未知（包含一条早期终止请求和两条transport error）。已知input=35,733、cached=0、output=80,121、total=115,854 tokens；49条守恒检查均通过。这些是已知小计，不是完整消耗或实付账单。五条首版复用调用只计一次。

180秒参数是socket timeout，不是端到端硬截止；完整canvas重建实际达到300.18秒，因此不能宣称所有请求wall-clock都限制在180秒。

指标命名澄清：历史JSON字段 `reconstruction_exact_fact_recall` 名称容易误导，实际应读作 answer-substring coverage。它不检查词边界和实体关系，短数字可能误匹配另一数字的子串，也不能识别语义改写；不能单独据此声称关键事实完整保留。冻结代码和原始数值未修改，报告采用准确标签。Probe QA的完全匹配分数与VLM judge仍单列。
