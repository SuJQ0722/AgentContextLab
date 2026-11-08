# SCO 实例与并发方案（待验收，未启动）

2026-11-08。用户要求先修复、push `dev`、检查 DSH/Hermes 图表环绕与 web 服务，确认后才开始实验。本文件和 [配置](../configs/sco-review-plan.json) 只准备部署，不解除暂停。

| 组别 | 实例划分 | 实例数 | 每台配置 | worker 并发上限合计 |
|---|---|---:|---|---:|
| 核心 BC-100 × 3 | 2 harness × 5 策略 | 10 | 8 vCPU / 32 GiB / 0 GPU / 32 worker | 320 |
| RQ3 BC-100 × 3 | Hermes 的 6 个额外分辨率，1x 复用新版核心对照 | 6 | 同上 | 192 |
| 受控 native-image baseline | visual / summarize_native / sliding_window_native；每种方法顺序覆盖多模态 benchmark | 3 | 同上 | 96 |
| 信息损失（条件项） | visual / summarize / text_only；各自覆盖分辨率、距离条件 | 3 | 同上 | 96 |
| 全部准备项 | 需要分别通过科学与运行门槛 | **22** | **176 vCPU / 704 GiB 合计** | **704** |

核心优先；前两组 16 台、512 worker。受控实验完整三 benchmark 的正式 protocol 与 cohort 尚需冻结，现有两 benchmark 固定前缀 pilot 不能代替。信息损失须先有新版有效源轨迹和可用 probe protocol，不能把旧失败 pilot 当作已就绪。计费、配额、完成时长未测，表中并发是配置上限，不是吞吐测量。

这是按最新“每实验每策略一台、每台 32”展开的**待确认方案**，全局 worker 数超过先前单机 128 进程限制。worker、OS 进程（含 Node/Python/renderer 子进程）、API in-flight、线程必须分别监测。8 核 32 GiB 是否承受 32 个最坏渲染轨迹尚未负载验证；不把这项配置写成已测容量。渲染峰值应排队并记录等待时间，CPU 线程数限制为 1，避免 32 个 worker 各自扩张线程池。

## CLI 与账号状态

已根据用户提供的 [SCO 介绍](https://console.cn-tj-01.sensecore.cn/help/docs/CLI/Introduction) 查阅其 [官方可访问页面](https://www.sensecore.cn/help/docs/CLI/Introduction)，并安装隔离的 SCO v2.0.4 到 `.tools/sco`；没有修改全局 PATH 或登录配置。`sco version` 与 `sco ssp jobs create --help` 成功。安装器在当前 AFS 上需要 `TAR_OPTIONS=--no-same-owner`，未更改文件系统属主。

官方 [SSP 参数化任务文档](https://www.sensecore.cn/help/docs/CLI/SCO_Refrence/SSP/jobs/create-params) 支持单 pod、0 GPU、8 CPU、32 GiB 以及 AFS 挂载；最终产品/region 必须以账号实际可用队列为准。AICL 的 [start](https://www.sensecore.cn/help/docs/CLI/SCO_Refrence/AICL/instances/start) 用于启动已有开发机，不能从该命令推断可以批量新建任意规格开发机。

本机尚无 active profile。一次含假占位 workspace/queue/image、命令 `exit 0` 的 `--dry-run` 被 CLI 拒绝：`no active profile found; run 'sco init' first`。**没有成功做云端配置校验，也没有创建资源。**尚缺真实 region、workspace、queue、镜像、AFS volume 与账号配置；不能从控制台 URL 推断 region code。不要把密钥放进提交、任务命令行或报告。API key 经私有挂载/环境注入，容器只得到必要凭据。

以下仅是供核对的官方参数形式，所有占位必须替换，启动命令必须换成验收后的版本化 runner：

```bash
sco ssp jobs create job-acl-review \
  --workspace-name <workspace> --queue-id <queue-resource-id> \
  --image <validated-image> --args 'exit 0' \
  --framework FRAMEWORK_CUSTOM --pod-count 1 \
  --cpu-count 8 --memory-gib 32 --gpu-count 0 \
  --volume-mount PV_AFS:<volume-id>:<mount-path> --dry-run
```

## 冻结、恢复与统计

新版代码必须生成新 campaign 与实现哈希。旧冻结运行目录、STOP、结果、已发生费用全部保留；旧视觉缺图结果不能当作新版已完成题目直接跳过。即使非视觉策略名称相同，只要 web 返回行为等改变，也不能自动混合两版本结果。

每台只负责其 experiment/harness/method 分片，每题/重复/attempt 唯一目录。跨机器恢复要使用机器 ID、owner epoch、heartbeat 与原子分片 lease；不能只拿另一台的 PID 去查本地 `/proc`，也不能原样复制目前单机 coordinator。终态结果跳过；中断重试必须保留原 attempt 与未知 usage，不得覆盖或填零。AFS 锁和原子更新须先在实例间验证。

每条请求保存 cached input、non-cache input、output、total 与缺失字段，单列 compaction、budget calibration、judge 消耗；逐调用检查 token 守恒。保存 search/fetch cache hit、压缩次数、原生图与渲染图哈希、最终 HTTP image ledger。客户端 API elapsed、端到端时间、渲染/排队时间分别记录；provider 内部延迟与未提供的图片 token 拆分保持缺失。实际美元成本需 TokenHub 对应 route 费率，不能假装 Gemini 价格是 DeepSeek 实付。

部署前先在各实例网络执行真实 search/fetch/Lens 检查，再检查 shared policy、图像最终 payload、native baseline 的匹配预算。用户验收截图和确切实例清单后才能解除暂停；成功离线测试本身不授权启动。

本地展开可审查矩阵（只写 JSON，不调用 SCO 或模型）：

```bash
python scripts/prepare_sco_review.py --out outputs/sco-review/instance-matrix.json
```
