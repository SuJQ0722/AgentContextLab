# RQ3：七档分辨率独立云节点

**历史部署记录：本页初始0.125档已被用户取消；最终范围、替换节点及实时统计入口见[最终七档](final-seven-cloud.md)。本页原配置表保留作切换来源，不是当前实验范围。**

用户明确要求每个分辨率一台 CCI、每台16并发。继续使用天津现有 SCO/ACP 资源入口、8 CPU / 32 GiB、私有 sjq-dev-cpu 镜像、afs_agents 挂载和原实验目录。

| 分辨率 | 固定云资源名 | 目标并发 | 固定科学样本 |
|---|---|---:|---:|
| 0x | acl-rq3-s0000-ops2 | 16 | 100题×3 |
| 0.125x | acl-rq3-s0125-ops2 | 16 | 100题×3 |
| 0.25x | acl-rq3-s0250-ops2 | 16 | 100题×3 |
| 0.5x | acl-rq3-s0500-ops2 | 16 | 100题×3 |
| 0.7x | acl-rq3-s0700-ops2 | 16 | 100题×3 |
| 0.8x | acl-rq3-s0800-ops2 | 16 | 100题×3 |
| 1x | acl-rq3-s1000-ops2 | 16 | 100题×3 |

112是目标worker并发，不是OS进程数或已完成样本数。每档300条包含已经完成和本机在途的原任务，绝不新增七份300条。模型、SFB路由、cohort、三repeat、分辨率配置、原生Hermes循环、工具约束、30分钟预算和科学源码均保持冻结；只调整运维派发。0x只移除远历史canvas，近期canvas仍保留。

本机ops1通过精确PID身份的pidfd SIGTERM停止新派发，原生子进程自然结束，Reader保持可用。每档新slots独立，原在途/未知预留仍占该档容量，过渡期新节点活跃数可能暂小于16。完整claim目录一次rename发布；旧claim、attempt、spec、未明确归属的暂存文件均不自动重跑。每档永久controller lease防止平台重启后重复启动；不启用云平台自动重试。

切换时的未启动预留为hermes/scale_0000/q_043_r01。它由独立recovery2保留原not_started与零API证据，只有原ops1完全排空且身份确认死亡后，才首次运行一次；与0x云节点共享16slots。原q085 recovery1保持不变。统计固定采用相应恢复，不按评分择优，也不增加第四repeat。

运行入口：

- `scripts/provision_rq3_scale_ops2.py`：默认dry-run，明确`--live`才创建资源；固定名称、请求与响应receipt防止不明create结果重复计费。
- `scripts/bootstrap_rq3_scale_ops2.py`：检查共享runtime/font/Poppler/Node与Reader，在各节点实际检查search/fetch，然后启动该档controller。
- `scripts/run_rq3_scale_cloud_ops2.py`：每档独立16名额，调用未修改的RQ3 trial/worker。
- `scripts/monitor_rq3_cloud_ops2.py --watch`：只读汇总，不调用模型。

实时证据：

- 原root：`outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3`
- 切换授权/旧停派ACK：`cloud-scale-ops2/cutover.json`、`local-stop-ack.json`
- 分档controller：`cloud-scale-ops2/controllers/<scale>/<id>/status.json`
- 汇总：`cloud-scale-ops2/monitor/status.json`
- 每节点资源/OS进程：`runtime/nodes/<host-boot>/telemetry.json`
- 云创建receipt：`outputs/cloud-runtime/rq3-scale-ops2-submissions/<name>/`
- 原生raw token/cache、压缩次数、图像检查：原`jobs/.../attempts/attempt_001/native/metrics/`
- 评分与avg3/std/CI：`outputs/grading/rq3-parity-v3-deepseek-sfb-v1/analysis/`

本机与云节点的运行阶段需在延迟/缓存分析中区分；云配置目标不替代实际运行量、provider内部延迟或模型计量。科学准确率按同题同repeat汇总，原始失败/费用与恢复成本保留。全部300条覆盖之前不提交完整avg3/std或显著性结论。

部署状态以真实创建receipt、节点心跳和native请求为准；本页配置表不代表七个资源已成功运行。
