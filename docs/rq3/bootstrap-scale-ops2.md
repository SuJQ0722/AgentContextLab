# RQ3 七分辨率云节点启动协议

独立运维入口：`scripts/bootstrap_rq3_scale_ops2.py`。不创建任何云资源，不修改旧 core bootstrap、RQ3 科学源码、原计划或原结果。每个 CCI 固定一个 scale，复用已审查私有镜像、`/mnt/afs_agents`、8 CPU / 32 GiB；每节点16个 trial，衍生渲染进程与线程不算作16个 OS 进程。

接受 `--scale 0/.125/.25/.5/.7/.8/1` 或对应 `scale_0000/0125/0250/0500/0700/0800/1000` 标签；canonical conversion 委托 `run_rq3_scale_cloud_ops2.normalize_scale`，不另造分辨率映射。固定根为 `outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3`。

默认或 `--dry` 仅打印启动计划，不启动服务、不访问网络、不调用模型。`--check` 检查 AFS位置、共享Python/字体/Node24/Poppler/Reader依赖与既有 `configs/cloud-runtime-v3.json`，并调用 `run_rq3_parity_v3.validate(plan,root)`；不调用核心 `validate_sources`。缺共享Python时仅live可按已审查stage manifest恢复，不修改共享venv或升级依赖。

显式 `--live` 还要求 `verify_cutover(root)` 通过（主控写入 `cloud-scale-ops2/cutover.json` 的启动授权和旧本机停止派发证据）。其后启动/复用本机固定 text Reader `127.0.0.1:18080`，使用既有32slot Reader运维配置与已配置研究代理，运行真实 Hermes `web_search/web_extract` 的host-scoped readiness，再启动：

```bash
python scripts/run_rq3_scale_cloud_ops2.py \
  --root outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3 \
  --scale scale_0125 --concurrency 16 --resume --live
```

provision可调用：

```bash
python scripts/bootstrap_rq3_scale_ops2.py \
  --root outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3 \
  --scale .125 --reader-python /opt/conda/bin/python --live
```

只有继承环境的基础运行键和显式代理允许进入子进程；SCO/AWS/SSH agent/model环境凭据不继承，模型凭据由原研究启动器读原research dotenv。research dotenv中若出现云provisioning凭据则拒绝。loopback始终加入NO_PROXY。共享git只在各节点 `/tmp` 串行 `git diff`，无跨host全局锁。

每节点使用与core bootstrap相同的node-local cell lock，避免误在同一实例叠加两个cell。每个容器epoch保存 `runtime/nodes/{hostname}-{boot_id}/{scale}/bootstrap.json`、`exit.json`、日志及operations SHA；重启保留旧epoch。Reader/source/version健康每15秒检查；失败或收到SIGTERM只通知controller停派，等待其自然drain后才关自有Reader和遥测，不向native发送信号，不重试模型调用。

每30秒 `runtime/nodes/{hostname}-{boot_id}/telemetry.json` 记录node-local OS活/僵尸数、该root的RQ3 controller/trial/worker角色及cgroup资源。使用独立 `rq3-scale-node-telemetry-ops2` schema，不把core角色计数冒称RQ3，不把这些进程数当API并发；角色数不包含renderer衍生进程，OS总数包含。

本文件和离线测试不表示云资源已创建或模型任务已启动，实际证据由主控的提交回执、host preflight、controller状态、claim和真实调用日志提供。
