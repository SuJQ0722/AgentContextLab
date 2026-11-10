# V5 inline 补跑的客户端延迟

运行 `python scripts/report_visual_transport_latency_v5.py --out outputs/reports/visual-inline-v5-client-latency` 生成 JSON 与 Markdown。脚本只读已有日志，不调用模型，不修改预测结果；按 plan 指定的 job 路径读取，避免递归遍历 harness 依赖目录。

V5 只补跑之前失败、超时或尚未启动的题次，所有历史 completed 均保留。因此报告属于条件补跑样本，不能当作完整 100×3 的代表均值，也不能直接与旧文本 baseline 的全体均值比较。新旧版本不混合。

| 指标 | 测量边界 |
|---|---|
| Dispatch → worker start | controller-dispatched 的时间到 worker-started 的时间；是派发与进程准备，不是排队时间。 |
| Worker initialization → first model attempt | worker-started 的 ISO 时间到 Python 首个 request_started 或 DSH 首个 final_inline_request 的 at_unix；包括依赖加载、AFS 等待和本地初始化，不能算作 API 延迟。 |
| Request upload | Python HTTP send-request-body 完成事件给出的阶段耗时。 |
| DSH time to body sent | undici 实际 bodySent 从该 HTTP attempt 开始的耗时，包含连接准备；与 Python 纯发送阶段分列。生成器输出完字节不视为网络上传完成。 |
| Response headers / first bytes / stream | 客户端观察到的响应阶段，不是服务商内部推理耗时。 |
| Quota backoff | 实际 client_wait_seconds；计划等待时长不冒充测量值。 |
| Render / SDK / native / trial E2E | 各自保留记录；可能互相包含，不能相加声称完整独立分解。 |

没有明确 enqueue 时间，排队待派发时间为 missing。没有 provider 内部计时，provider inference latency 始终为 missing。正在运行的 trial 没有终态 E2E，也保持 missing。

实际 HTTP 请求按 trial attempt 路径、ledger、实际 route 与 request_id（DSH 为 attempt_id）区分；同一个 SDK 请求的四渠道尝试不能合并。Python 使用 `route`，DSH 使用 `actual_model`，不从初始配置猜实际渠道。

报告另列一次 10 张独立图像、5.28 MB、64 KiB 分块直传的 HTTP 200 诊断样例，明确它不是 benchmark 代表性延迟，不纳入实验统计。

验证：`python -m unittest discover -s tests -p test_visual_transport_latency_v5.py -v`，5 项通过，覆盖渠道尝试分离、实际退避、缺失值、部分日志及初始化耗时与 API 耗时分离。
