# VERA 选择性重跑：独立批次

用户要求保留正确题、重跑其余题并使用多个CCI。本批次先执行本轮明确修复的MMBC Hermes VERA；额外BC/RQ3范围仍待确认。

- 原300条中26条正确保留，274条进入一次新尝试：3条完成但答错、271条失败或超时。
- 新根目录：`outputs/campaigns/mmbc-vera-bounded-retry-v1`，plan SHA256 `776ccc698d4ab727847553ef4bc394d63511169f3a466bb07898eb5a2560d5fb`。
- 三个不重叠分片为92/91/91，各16并发，全局最多48个预测worker。全部8核32GiB、原指定私有镜像、`afs_agents`共享目录。
- 使用bounded分页、远历史.75、recent1.0独立小页、逐像素一致WebP、最终8MiB/32图守卫。原生图不改字节，工具仍仅search/fetch/image_search/crop/zoom，模型不可使用文件或shell工具。
- 每条最多新增一次attempt；编排器不重新派发未知attempt或claim，不反复跑到答对。原生Hermes/SDK已有的有限API重试策略保持原配置，所有实际HTTP尝试及缺失usage仍须计账。

旧轨迹没有物理删除：保留原目录作为不可变档案，新活跃队列仅保留正确结果的引用，并将其他题设为新尝试待运行。这样保留原失败、原token消耗和来源证据；也避免删除后无法核查累计成本。worker spec不携带旧答案、评分理由或正确性标签。

结果须分开报告：原300条首次结果；274条新尝试的条件准确率；保留26条旧正确结果再合入新结果的union。最后一项是依据旧答案选择重跑、且混合新旧renderer的结果，**不能作为普通单次avg3、不能据此声称对baseline有统计显著优势**。全部新旧尝试、判断请求及未知usage须保留计费和缓存统计。

新控制器跨节点claim永久保留，按分片独占lease；停止派发后自然等待已运行worker结束。每个CCI先检查实际search/fetch服务。独立评分watch最多2并发，所有结果终态且可评分任务都已尝试后退出。独立生命周期watch只有在实例UID、命令/镜像、计划、controller退出和全部子任务清理证据一致时才暂停本次CCI；不自动重启或重复未知创建/停止请求。

部署名称：`acl-mmbc-vera-bounded-r1-s0`、`acl-mmbc-vera-bounded-r1-s1`、`acl-mmbc-vera-bounded-r1-s2`。48是预测worker上限，不是操作系统总进程数；trial、Reader、controller、渲染子进程和评分另行计数。

测试：本轮根目录600项通过；评分器另7项定向测试通过。运行证据位于新root的`controllers`、`runtime/nodes`、`jobs`以及`outputs/cloud-runtime/bounded-vera-retry-v1`。评分输出位于`outputs/grading/mmbc-vera-bounded-retry-v1`。

## 启动实测

2026-11-10 03:38 UTC观察：三个CCI各16个预测任务运行，启动后观察约5分钟；评分器与生命周期watch存活。164/195题的10页/8页压缩后请求已成功返回并继续工具调用。064/130题分别有14/14、10/10来源图被完整渲染，刚渲染的证据不能冒充模型已经读懂。全局存在少量API超时并保留未知usage；最早6条样本的44个返回调用计量完整且守恒。审计`outputs/preflight/bounded-vera-retry-live-audit-v1/report.json`，运行快照`outputs/campaigns/mmbc-vera-bounded-retry-v1/operations/startup-observed.json`。
