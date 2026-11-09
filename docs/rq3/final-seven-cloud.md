# RQ3 最终七档：每档 100×3

2026-11-09 用户最终范围为 **0、0.25、0.5、0.7、0.75、0.8、1.0**。每档固定同一批100题、3个repeat，共2100个观测；0.125排除，旧轨迹和调用费用保留。目标每档一台8 CPU / 32 GiB云节点、16个原生任务，共112个任务槽。任务槽不等于HTTP同时请求数或操作系统进程数。

截至07:47 UTC的实测部署状态：

| 分辨率 | 云资源 | 活跃原生任务槽 | 状态 |
|---|---|---:|---|
| 0x | acl-rq3-s0000-ops2 | 16 | 已实际运行 |
| 0.25x | acl-rq3-s0250-ops2 | 16 | 已实际运行 |
| 0.5x | acl-rq3-s0500-ops2 | 16 | 已实际运行 |
| 0.7x | acl-rq3-s0700-ops2 | 16 | 已实际运行 |
| 0.75x | acl-rq3-s0750-ops3 | 0 | 平台STARTING，worker Pending |
| 0.8x | acl-rq3-s0800-ops4 | 16 | 已实际运行 |
| 1x | acl-rq3-s1000-ops4 | 0 | 平台STARTING，worker Pending |

资源使用已有的SCO/ACP training-job入口；不是CCI apps资源。最初后三档转入同工作区rl、同可用区和VPC的agentic-rl池，但持续未调度。agents池释放8 CPU后，0.8的从未启动资源经确认停止后迁回并实际运行；1x转到同规格、同VPC、已有同AFS运行证据的code池，仍待调度；0.75暂留agentic-rl。迁移只涉及从未启动的节点，没有重放预测。镜像仍为私有sjq-dev-cpu，挂载afs_agents，实验目录不变。池的聚合空闲CPU不能证明节点已调度；真实启动必须有bootstrap、controller心跳和native返回。

六个不变分辨率继续复用`rq3-deepseek-bc100-r3-parity-v3`的既有有效观测。原计划、科学源码和旧结果保持冻结。新增0.75使用独立`rq3-deepseek-bc100-r3-scale0750-v1`，只授权300个0.75任务；其结构计划里的其他1800条占位不运行。新入口经过原生图像guard与远历史缩放检查，近期画布像素不变。

0x是远历史画布缩放策略中的零档；近期画布仍保留，不等于整个agent完全没有图像。原q085和q043两个有证据的首次启动恢复按固定来源替换相应观测，不构成第四repeat，不按分数择优。

最终统计与监控入口：

- `outputs/supervision/rq3-final-seven-runtime.json`：七档真实活跃任务与状态，只读watch，零模型调用。
- `outputs/grading/rq3-final-seven-v1/summary.md`、`statistics.json`：六档旧root加新0.75的固定2100观测。
- 同目录`comparison-plan.json`：固定来源映射与哈希；`excluded-scale0125-cost.json`单列被排除运行的费用/缺失计量。
- `outputs/grading/rq3-parity-v3-deepseek-sfb-v1`：原六档评分，新增派发明确过滤0.125。
- `outputs/grading/rq3-scale0750-v1`：新增0.75独立评分，只接受300项allowlist。
- `outputs/cloud-runtime/rq3-capacity-ops3`及`rq3-capacity-ops4`：容量迁移、旧节点停止与从未启动证据、新节点创建receipt。

raw cached/non-cache/output token、API客户端耗时、端到端时间、渲染开销继续分别记录；缺失字段为unknown。完整300条覆盖之前不发布完整avg3±std、bootstrap CI或配对显著性结论。0.125费用不会通过排除科学比较而消失。

验证：根目录419项单元测试通过；0.75另有零付费的真实native/crop/zoom/压缩HTTP图像guard和跨尺度像素fixture。云节点运行状态属于实测快照，不能用配置目标替代。

资源池聚合空闲不等于CPU-only实例可调度容量。官方CLI未返回Pending的FailedScheduling事件；节点CPU-only/成员限额仍待平台证据，不能断言具体根因。只读诊断保存于`outputs/preflight/rq3-pending-diagnosis-20261109/`。当前没有通过调高优先级或更改共享集群限额抢占其他任务。
