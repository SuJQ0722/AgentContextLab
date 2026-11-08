# SCO 实例与并发方案（已授权，天津认证通过，云实例尚未创建）

2026-11-08。用户要求先修复、push `dev`、检查 DSH/Hermes 图表环绕与 web 服务，确认后才开始实验。用户随后明确回复“没问题，resume目前运行结果，开始吧”，已授权启动；授权记录位于 `outputs/authorization/resume-v3.json`。本文件和 [配置](../configs/sco-review-plan.json) 记录部署范围，天津首台核心实例 `acl-bc-v3-hermes-visual` 已于 2026-11-08 08:00:58 UTC 创建；运行时和真实 web 预检通过，正在核对实际模型调用。其余实例在首台运行确认后展开。

| 组别 | 实例划分 | 实例数 | 每台配置 | worker 并发上限合计 |
|---|---|---:|---|---:|
| 核心 BC-100 × 3 | 2 harness × 5 策略 | 10 | 8 vCPU / 32 GiB / 0 GPU / 32 worker | 320 |
| RQ3 BC-100 × 3 | Hermes 的 6 个额外分辨率，1x 复用新版核心对照 | 6 | 同上 | 192 |
| 受控 native-image baseline | visual / summarize_native / sliding_window_native；每种方法顺序覆盖多模态 benchmark | 3 | 同上 | 96 |
| 信息损失（条件项） | visual / summarize / text_only；各自覆盖分辨率、距离条件 | 3 | 同上 | 96 |
| 全部准备项 | 需要分别通过科学与运行门槛 | **22** | **176 vCPU / 704 GiB 合计** | **704** |

核心优先；前两组 16 台、512 worker。受控实验完整三 benchmark 的正式 protocol 与 cohort 尚需冻结，现有两 benchmark 固定前缀 pilot 不能代替。信息损失须先有新版有效源轨迹和可用 probe protocol，不能把旧失败 pilot 当作已就绪。计费、配额、完成时长未测，表中并发是配置上限，不是吞吐测量。

这是按最新“每实验每策略一台、每台 32”展开的**已获用户授权的方案**，全局 worker 数超过先前单机 128 进程限制。worker、OS 进程（含 Node/Python/renderer 子进程）、API in-flight、线程必须分别监测。8 核 32 GiB 是否承受 32 个最坏渲染轨迹尚未负载验证；不把这项配置写成已测容量。渲染峰值应排队并记录等待时间，CPU 线程数限制为 1，避免 32 个 worker 各自扩张线程池。

## CLI 与账号状态

天津专用 SCO CLI **v1.3.0** 已安装在 `.tools/sco-tj/cli/sco`，profile `agentcontextlab-tj` 已认证成功。采用 [天津官方 CLI 文档](https://console.cn-tj-01.sensecore.cn/micro/help/docs/CLI/Introduction/) 的区域包与元数据；此前 `.tools/sco` 的通用 v2.0.4 及 SSP 示例不适用于本次天津部署。创建入口为 [ACP `jobs create`](https://console.cn-tj-01.sensecore.cn/micro/help/docs/CLI/SCO_Refrence/ACP/instances/create/)，而非通用 `ssp jobs create`。

以下为认证后的非秘密资源查询结果，**云实例尚未创建**：

| 项目 | 已核验值 |
|---|---|
| Region / zone | `cn-tj-01` / `cn-tj-01a` |
| Workspace | `rl` |
| Subscription | `019e1f63-b10b-78d7-a6da-2b39e0790662` |
| Resource group | `default` |
| 算力池 | `agents` |
| Worker spec | `N4lS.Iu.I80.8c32g`；查询返回 CPU 8、内存 32 GiB、`chip_count=0` |
| AFS | `afs_agents`，ID `019ed8e0-f4f8-71f7-830c-f8a1e667a9ec` |
| 挂载路径 | `/mnt/afs_agents` |
| 私有镜像 | `registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401` |
| 镜像 digest | 尚未查询，保持未知；tag 不等同于不可变 digest |

工作目录为 `/mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab`，结果写入其 `outputs/` 下的新版本目录。密钥只保存在私有配置，不进入提交、任务命令行或报告。容器通过私有挂载/环境获得必要 API 凭据。

ACP 按实际池与 worker spec 选择资源。供部署脚本核对的命令形式如下；`<versioned-bootstrap-command>` 必须替换为验收后的启动脚本，以下示例未执行，不代表云任务已经创建：

```bash
.tools/sco-tj/cli/sco acp jobs create \
  --workspace-name rl --aec2-name agents \
  --job-name <unique-job-display-name> \
  --container-image-url registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401 \
  --training-framework pytorch --worker-nodes 1 \
  --worker-spec N4lS.Iu.I80.8c32g \
  --storage-mount 019ed8e0-f4f8-71f7-830c-f8a1e667a9ec:/mnt/afs_agents \
  --command '<versioned-bootstrap-command>'
```

区域 CLI 的实际组件帮助及服务端校验优先于通用 CLI 参数。此处不添加未验证的 `--dry-run`，也不启用自动容错重试来重复执行可能已经发生付费调用的任务。

## 冻结、恢复与统计

新版代码必须生成新 campaign 与实现哈希。旧冻结运行目录、STOP、结果、已发生费用全部保留；旧视觉缺图结果不能当作新版已完成题目直接跳过。即使非视觉策略名称相同，只要 web 返回行为等改变，也不能自动混合两版本结果。

核心 v3 已在本机运行，目录为 `outputs/campaigns/bc100-r3-hermes-parity-v3`。本机继续参与同一调度：本机与后续云控制器共享 AFS 上的原子 job claim 和每个 harness/strategy cell 的 slots，**每个 cell 的跨主机总 worker 上限为 32**，不是本机 32 再叠加每台云机 32。终态结果跳过，已有 claim 不自动重试；中断或未知状态保留原 attempt、usage 与 owner 证据，避免重复付费。

每台只负责指定 experiment/harness/method 分片，每题/重复/attempt 唯一目录。跨机器身份包含 hostname、boot ID、PID namespace 和 start identity，不能只拿另一台 PID 查本地 `/proc`。多机 AFS 锁、原子更新和恢复行为仍须在实际实例间验证；本机运行通过不能替代跨主机验证。其他实验组保持表述中的未就绪状态，不因账号认证通过而自动启动。

每条请求保存 cached input、non-cache input、output、total 与缺失字段，单列 compaction、budget calibration、judge 消耗；逐调用检查 token 守恒。保存 search/fetch cache hit、压缩次数、原生图与渲染图哈希、最终 HTTP image ledger。客户端 API elapsed、端到端时间、渲染/排队时间分别记录；provider 内部延迟与未提供的图片 token 拆分保持缺失。实际美元成本需 TokenHub 对应 route 费率，不能假装 Gemini 价格是 DeepSeek 实付。

部署前先在各实例网络执行真实 search/fetch/Lens 检查，再检查 shared policy、图像最终 payload、native baseline 的匹配预算。用户已验收并授权启动。天津认证与上述资源查询已完成；云部署仍须完成实例启动后的网络与共享存储校验。当前本机核心 v3 运行与云实例尚未创建须分开报告。

本地展开可审查矩阵（只写 JSON，不调用 SCO 或模型）：

```bash
python scripts/prepare_sco_review.py --out outputs/sco-review/instance-matrix.json
```

## 工具访问范围

核心两个 harness 从首次请求起仅开放 `web_search`、`web_extract`、`image_search`、`image_crop`、`image_zoom_in`。文件读取、目录检索、终端、代码执行、委派等不在白名单；同时关闭自动工作目录 instructions。新版 DSH 非 BC-100 入口当前拒绝运行，避免绕回旧数据任务工具集。AFS 为运行程序、日志及数据加载器挂载，不等同于向模型开放文件工具。imgBB key 通过当前 Hermes 私有 `.env.local` 单项注入，不进入镜像、提交或任务命令行。
