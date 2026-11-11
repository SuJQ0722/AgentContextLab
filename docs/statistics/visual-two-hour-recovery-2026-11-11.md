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
