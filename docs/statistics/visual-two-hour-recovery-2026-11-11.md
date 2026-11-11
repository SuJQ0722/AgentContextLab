# 两小时视觉补跑批次（2026-11-11）

整题超时统一改为 **7,200 秒**。AgenticDataBench 不补测。本次为既有失败轨迹的恢复批次，不是新增独立的 avg@3。

当前启动入口使用 `configs/experiment.json` 的 `visual_inline_two_hour_v7` 段及据此冻结的每组配置；旧 campaign 段保留其原始协议时限，供历史验证使用，不是本次运行入口。

## 超时问题的现状

不能宣称超时已完全解决。此前已经移除压缩图像上传图床，改为直接传入最近最多 10 张图；修复网关代理路径后，Hermes 和 DSH 均已有带压缩图像的成功 API 响应。然而，多轮推理和渠道失败仍可能耗尽原来的 30 分钟整题预算。

本次同时对齐控制器、原生 worker、传输层的整题截止。DSH 的 JavaScript 传输层原有固定 30 分钟截止已移除；SDK HTTP 和 idle watchdog 均显式设为 7,200 秒。DSH 旧控制器额外加 240 秒的行为也已移除。控制器约每两秒检查一次；终止后的进程清理时间可能使记录的端到端 wall time 略超过 7,200 秒，不代表继续给予模型预算。

单次 HTTP 尝试仍为 300 秒，按既有四渠道策略恢复；输出预算仍为 8,192 tokens。延长整题时限不能保证消除渠道超时或 output-limit 失败。

## 恢复范围

从原 V5 的 1,536 个槽位及其后继恢复记录中，仅选择最新执行失败或超时、且历史没有 completed 的槽位。保留 302 条已完成轨迹，包括答错的；待恢复 1,234 条。选择不读取答案或评分。

| 实验 | 待恢复轨迹 | 每组并发 |
|---|---:|---:|
| BC / Hermes | 71 | 16 |
| BC / DSH | 96 | 16 |
| RQ3 / 0x | 73 | 16 |
| RQ3 / 0.25x | 78 | 16 |
| RQ3 / 0.5x | 88 | 16 |
| RQ3 / 0.7x | 101 | 16 |
| RQ3 / 0.75x | 99 | 16 |
| RQ3 / 0.8x | 100 | 16 |
| RQ3 / 1.0x | 83 | 16 |
| MMBC / VERA | 208 | 16 |
| MMBC / vanilla | 213 | 16 |
| 受控 / BC / visual | 12 | 16（实际最多 12） |
| 受控 / MMBC / visual | 12 | 16（实际最多 12） |

24 条受控任务的原始图像、prefix 和 ledger 已校验，对应 29 个原始输入图像文件；恢复直接复用这些字节，避免重复下载导致输入阶段失败。

部署安排为本机两个 BC 组和 11 个独立 CCI；每组固定 16 并发，无全局推理并发上限。新结果目录为 `outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v7-two-hour`。本文件记录恢复定义；实际启动和存活状态以该目录的启动收据与监控记录为准。

旧结果、旧超时、原始费用记录全部保留。两小时恢复产生的 token、缓存、延迟和评分单独记录；缺失的 provider usage 不按零计算，客户端请求耗时不称为 provider 内部 API 延迟。跨版本合并的成功率应注明失败恢复与成功条件筛选，不能视为同一协议重新运行的完整基准结果。

## 启动验证

完整根目录测试：980 项通过，153.072 秒（`/tmp/acl-two-hour-v7-tests-final.log`）。13 组真实原生入口 dry-run 均退出 0，未调用模型；所有 job/config/native outer deadline 均为 7,200 秒。证据位于 `outputs/preflight/visual-inline-two-hour-v7/readiness.json` 与 `native-dryrun/results.json`。

## 运行及排期快照

2026-11-11 04:43 UTC（北京时间 12:43）本机 BC Hermes、DSH 各以 16 并发启动。两组均已产生完整模型响应及完成轨迹；评分 HTTP 429 单独记录，交由独立四渠道评分恢复，不重跑预测。

截至 2026-11-11 05:16 UTC（北京时间 13:16），13 组均已进入实际执行，现场合计 199 条活跃任务。部署位置为：

- 本机：BC Hermes、BC DSH。
- `toolcall-server`：受控 BC、MMBC VERA。
- `agentic-rl`：受控 MMBC、MMBC vanilla、七组 RQ3。

原 `agents`、`dev-infra`、`toolcall` 池受到更高优先级训练任务的队列阻塞，已将尚未启动的相关任务安全迁出。每次迁移均保留旧 UID 停稳、前后零执行证据及新 UID/配置绑定；已运行任务未迁移。每组仍固定 8 核 32G、16 并发，预测 plan、输入图像和两小时时限未变。各新部署有独立生命周期监控，完成并确认子进程退出后释放实例。

北京时间 13:19 的进一步核验确认：全部 13 组均已有完整 HTTP 响应及原始 provider usage，六项持久服务均存活。该非原子快照记录已完成 14 条、失败 3 条；失败包括 MMBC VERA 两条远程缩略图下载 TLS EOF，以及 DSH 原生 image offload 后图片数量与 wire guard 预期不符导致的本地拒绝发送（表面显示 Connection error），不能报告为零失败或超时问题已根治。各组仍持续取新题，原始错误、费用和失败结果保留。证据：`outputs/preflight/visual-inline-two-hour-v7/live-startup-snapshot.json`、`service-health.json`。三条失败的根因与证据另见 `outputs/preflight/visual-inline-v7-execution-failure-diagnosis/diagnosis.json`。

以下是按每题耗尽两小时预算、每组 16 并发计算的波次工期，**不是实测平均耗时或承诺截止时间**；不包含排队、初始化、清理、评分及额外补跑：

| 组别 | 预算工期 |
|---|---:|
| BC Hermes | 10 小时 |
| BC DSH | 12 小时 |
| 两组受控实验，各自 | 2 小时 |
| RQ3，各分辨率 | 10–14 小时 |
| MMBC VERA | 26 小时 |
| MMBC vanilla | 28 小时 |

保守排期（北京时间，包含少量清理和评分余量）：

| 组别 | 计划收尾时间 |
|---|---|
| BC Hermes | 11 月 11 日 23:30 左右 |
| BC DSH | 11 月 12 日 01:30 左右 |
| 两组受控实验 | 11 月 11 日 16:00 左右 |
| 七组 RQ3 | 11 月 12 日 04:00 左右 |
| MMBC VERA、vanilla | 11 月 12 日 20:00 左右 |

**本轮补跑与评分整体目标：北京时间 2026-11-12 20:00 左右。** 这是按两小时整题预算计算的保守规划，尚不是基于完整新批次吞吐的统计预测；不包含未来另行决定的再次补跑。实际完成可更早，后续平台中断或持续渠道错误也可能使计划顺延。已经完成的轨迹继续保留，不因评分结果重跑。
