# V5 运行层诊断与 V6 小规模验证

2026-11-11，只读核对全部 1536 个计划题次。运行侧结果位于 `outputs/preflight/visual-inline-v5-runtime-diagnosis/initialization.json`，不读取答案或按得分选样本。

| 执行位置 / 方法 | 前16个有首请求记录题次的初始化中位秒 | 后续初始化中位秒 |
|---|---:|---:|
| 本机 BC Hermes | 385.5 | 17.4 |
| 本机 BC DSH | 737.7 | 34.6 |
| CCI MMBC VERA | 24.2 | 10.7 |
| CCI MMBC vanilla | 24.0 | 10.8 |
| CCI RQ3 各分辨率 | 15.7–22.8 | 11.5–15.3 |

表格按worker启动时间排序，零模型调用且没有首请求记录的题次不进入初始化统计。初始化是 worker-started 到首个模型 HTTP attempt 的客户端实测时间，包含依赖加载和 AFS 等待。原运行的 `/proc` 证据显示本机 Node/Python 依赖访问等待 FUSE 元数据；首批之后明显缓解。但后续本机及云端仍大量超时，AFS 冷启动不足以解释全局问题。

主实验 timeout 的终态 E2E 中位约1801秒，受控约3601秒，与原墙钟限制相符。受控初始化仅约18–21秒。应继续分解实际上传、响应、退避与多轮调用，而不是将超时全部归因到文件系统或仅延长时限。

V6 canary 只选择8个既往 timeout：BC双harness、MMBC VERA/vanilla、RQ3 0.75/1.0、受控BC/MMBC各1题。保留题目、重复编号、上下文、最大输出、分辨率和墙钟时限。选择检查历史completed并排除之；不复跑已完成题。独立目录 `outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v6-canary`，每cell配置16并发但只有1个冻结任务。

新版显式记录 runtime v4 与 gateway proxy，不修改旧冻结源。Python验证专属代理client绕过旧NO_PROXY设置的影响；DSH的JS实现与SDK watchdog版本另行记录，不宣称其执行Python runtime。源码冻结、8题原生命令dry-run和针对性测试通过后，须由主代理放行live。小规模结果不能当作准确率提升证据，整批恢复仍需另行决定。

后续恢复保持旧结果只读、新attempt命名空间、同题seed绑定、claim与slot隔离、每题最多一次新尝试。若要改变时限或科学预算，应再立实验条件，而不能混入本canary。
