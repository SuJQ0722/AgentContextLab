# 实验 3：原生图像受控 baseline

## 当前结果：两条 capture 超时，fresh 校准已阻断

截至 2026-11-07，两条原定题目的 `result.json` 均为 `not_reached / 1800s_wall_timeout`。都未达到 32,768 provider prompt 阈值，未生成合格的 `prefix-manifest.json`。没有重跑、延长、改阈值或替换简单题。

| Capture | 请求启动 / 有返回 | 最大已测 prompt | 已知 cached input | 已知 non-cache input | 已知 output | 已知 total | 无返回请求 |
|---|---:|---:|---:|---:|---:|---:|---:|
| browsecomp_v3 | 10 / 10 | 22,975 | 108,800 | 23,677 | 11,572 | 144,049 | 0 |
| mmbrowsecomp | 10 / 9 | 17,503 | 84,992 | 17,810 | 26,469 | 129,271 | 1 |

BC V3 全部 10 次调用的 usage 已返回；MMBrowseComp 第 10 次请求被 wall-time 上限中断，usage 未知，因此其表中 token 均为已知小计，不能视为最终账单。可核验调用均满足 prompt+output=total；客户端流耗时不等于 provider 内部 API latency。

直接终止原因是 1800 秒墙钟上限，而非达到 60 轮或 context 上限。BC V3 多次调用耗时约 185–215 秒；MMBrowseComp 两次已返回调用产生 8192 output tokens，主要为 reasoning。部分调用之间也存在约 180 秒间隔，不能仅凭间隔断定其具体工具/网络原因。当前证据不支持将延迟归因于视觉压缩——本阶段压缩关闭。

原始请求/响应 gzip 均能完整读取：BC V3 10 份 request / 10 份 response，MMBrowseComp 10 / 9。最后归档请求分别包含 14 / 2 个原生 image parts；这些像素证据保留在轨迹中，但该请求并非达到阈值后捕获的正式 prefix，不能冒充受控压缩输入。

`prefix-capture/fresh-stage.json` 已为 `blocked`（原因 `browsecomp_v3 capture not_reached`）；fresh 输出目录未创建，fresh 付费请求为 **0**。因此实验 3 的正式 baseline **未启动、未完成**。旧历史校准数据保持不变。

可继续的零 API 工作是对已有归档逐图重建 ledger、审计检索/crop/zoom保留、复核成本与延迟缺失；不能把这些离线材料当成正式准确率实验。现有协议下没有已满足准入条件的新付费实验 3 阶段；重新采样、延长或更改触发阈值需要另行声明实验设置。详细终止与 usage 审计保存在 `outputs/experiment3/capture-terminal-audit.json`。

此前执行的是预算校准和真实多模态 prefix 采集，**尚未启动或完成正式 baseline benchmark**。所有新调用使用配置中的 DeepSeek，BC 主实验保留 16 并发。

两个 prefix capture（BrowseComp V3、MMBrowseComp）曾并行执行，最多 2 条；每条最多 60 轮、1800 秒。只有 `/proc` 可见活进程少于 104、包括僵尸的可见进程少于 128、总辅助模型 worker 少于 6 时才准入。调度器不再等待旧预算校准。AgenticDataBench 的沙箱不可用，未启动。

`outputs/experiment3/status.json` 每 30 秒更新进程、使用量及捕获状态；`status-history.jsonl` 保留快照索引。每条 trajectory 的原始 request/response、API usage、缓存计数和失败未知量保留在 `prefix-capture/<dataset>/metrics/`。不得将未知 usage 当零，也不得把客户端 stream/HTTP 时间当 provider API latency。

捕获阈值使用前一次 provider 返回的 prompt tokens ≥ 32768，在下一次请求发送前保存完整 request，包含原生 image/crop/zoom 像素与 SHA256、尺寸 ledger；该捕获请求本身未发送，不能将上一调用 token 数当作其精确 token 数。保存后的 `started.json` 阻止自动重跑付费调用；意外退出保留原轨迹与 usage，不能悄悄重试。

旧历史 prefix 校准已经结束：BC V3 与 MMBrowseComp 的 visual 测量均未获得 usage；sliding-window 的实测 prompt 分别为 25,601 与 17,314，超过 16,384 预算。历史导出也无法认证检索图、crop、zoom 完整像素，因此 formal gate 不通过。阈值和预算不会为通过校准而放宽。

校准代码已在旧进程结束后修复：summary/window 文本剥离内嵌图像/base64；按各实际 request 核验 native ledger；resume 校验 request/config 指纹。新捕获完成后，可在新输出目录准备 fresh-prefix 校准（默认零 API 调用）：

```bash
python scripts/controlled_native_preflight.py \
  --prefix-capture-root outputs/experiment3/prefix-capture \
  --output outputs/experiment3/fresh-native-budget-preflight
```

该命令要求两个捕获文件完整且 hash 一致。后续 live 校准仍有独立 12-call 上限；不等于正式两 baseline 与 VERA 的准确率对比。正式实验仍须满足原生图像一致、post-compression 总预算约束与实际 token 利用差异检查。预算匹配不能用字符数估算替代 provider usage。

## 自动衔接 fresh 校准

Queue 会等待原始两条 capture 均为 `captured`，并逐一验证 prefix SHA256。随后先在 `outputs/experiment3/native-budget-preflight-fresh` 零 API 准备并校验完整图像 ledger，再重新检查资源准入，最多启动一次独立 12-call 校准。`prefix-capture/fresh-stage.json` 记录 waiting/running/completed/blocked；新目录的 `stage-started.json` 保存 PID 和启动身份，queue 重启仅接管现有进程，不重复派发。

任一 capture 超时、正常结束却未达阈值、hash 不符或丢失完整结果，fresh stage 标记 blocked；不延长轨迹、不换题、不自动重跑。已启动但身份失效的校准同样保留未知调用并阻止自动重试。prepared 且没有发出任何请求的目录可通过 `--resume` 首次启动。旧历史校准目录保持不变。

专属监控持续覆盖 fresh stage 和其 usage；两条 capture 结束后不会提前停止监控。即使 fresh 校准结束，仍不表示正式 baseline 已启动或完成，必须检查预算 gate。两条本地模拟 capture 的零 API fixture 已验证图像像素有独立 ledger、文本中没有 base64，hash 错误和未知已启动阶段均会阻断。
