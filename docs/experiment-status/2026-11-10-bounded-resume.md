# Bounded resume 实验进展：2026-11-10

主快照：**2026-11-10 06:58:54 UTC**。工具日志补查截至 07:00 UTC。本页是该时点的只读统计；运行中的计数会继续变化。未触发任何新模型调用。

当前 BC 两个 harness 各 16 并发；RQ3 的 0、0.25、0.5、0.7、0.75 五档各 16 并发。0.8 与 1.0 已自然排空、CCI 为 SUSPENDED，等待 BC 完成后由容量调度器自动恢复。

## 当前队列

“completed”表示预测执行结束，是否答对单独列出；待运行与正在运行均计入“尚未终态”。表中的新尝试是恢复队列，并非重新独立抽取的完整 avg@3。

| 队列 | 新尝试计划 | 活跃 worker / 上限 | completed | timeout | failed | 已评分 completed / 答对 | 尚未终态 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BC Hermes | 113 | 16 / 16 | 1 | 0 | 0 | 1 / 0 | 112 |
| BC DSH | 137 | 16 / 16 | 3 | 0 | 1 | 3 / 2 | 133 |
| RQ3 0x | 159 | 16 / 16 | 17 | 11 | 0 | 17 / 17 | 131 |
| RQ3 0.25x | 163 | 16 / 16 | 18 | 16 | 0 | 18 / 16 | 129 |
| RQ3 0.5x | 177 | 16 / 16 | 12 | 15 | 0 | 12 / 12 | 150 |
| RQ3 0.7x | 192 | 16 / 16 | 11 | 15 | 0 | 11 / 11 | 166 |
| RQ3 0.75x | 176 | 16 / 16 | 10 | 16 | 0 | 10 / 9 | 150 |
| RQ3 0.8x | 178 | 0 / 16 | 9 | 13 | 0 | 9 / 9 | 156 |
| RQ3 1x | 182 | 0 / 16 | 11 | 7 | 0 | 11 / 11 | 164 |

RQ3 新恢复队列合计 1,227 次，其中 181 次终态：88 completed、93 timeout；88 条 completed 均已有有效评分，85 条答对。其余 1,046 条包括正在执行和未派发任务。原每档 100×3 的定义保留；这里仅计入原执行失败/超时选中的新尝试。

BC 新恢复队列共 250 次：Hermes 113、DSH 137；最新 4 条 completed 均已有评分，另有 DSH 1 条 failed。旧正确轨迹被保留，因此旧结果加新恢复结果属于按答案选择的混合尝试，不能标成全新独立 avg@3 或据此声称显著性。当前没有新的完整 avg@3 均值和标准差。

## 已结束及本机实验

| 实验 | 当前事实 | 尚缺内容 |
|---|---|---|
| MMBC VERA bounded retry | 274/274 新尝试终态：28 completed、224 timeout、22 failed；27 条 completed 有效评分，其中 18 条正确 | 1 条 judge 输出无效；该队列运行结束不等于实验结果可靠或成功 |
| 受控 baseline bounded pilot | 本机 1 worker；首个 visual 校准仍在运行，child PID 558901 存活；记录 4 次 APIConnectionError，控制 gate 尚未通过 | 尚无匹配成功的三臂组；其余 pilot 臂等待 visual 目标，不能宣称受控 baseline 已完成 |
| 信息损失 v2 | 固定 6 窗口完成：30 重建、25 ProbeQA 正常；25 次语义评分中 24 次成功 | q009 late / canvas 0.5 的语义评分 ConnectTimeout，3 个事实评分记 NA，不自动重试 |

受控队列原有 60 个组，40 组源前缀可用；当前仅两组 pilot（6 臂）逐个运行，尚未放行完整 120 个可用臂。本轮并未补齐原要求的三个多模态 benchmark 覆盖。APIConnectionError 是校准过程故障，不应写成方法控制失败或有效结果。

信息损失共 92 个 unique 请求尝试：38 次复用旧 request/response，54 次新调用，未重复付费阶段。91 次可计量响应：cached input 2,176、non-cache input 27,243、output 7,410、total 36,829；另 1 次 usage 未知。这是 **q004 development 与 q009 holdout 的短窗口诊断**，不是整个信息损失研究完成，也不能支撑总体显著性。详见 [诊断结果](../../outputs/experiment6/bounded-window-five-arm-v2/report.md)。

## 并发与真实 OS 进程数

容量调度器记录：RQ3 80 + BC 32 + 其他保留 8 = **120 / 128 slots**。保留 8 包括评分类任务、受控 worker 与信息损失预留；信息损失已结束但保留量尚未下调，计算仍偏保守。MMBC 当前为 0。这里 128 限制的是可派发的推理/实验任务容量，既不是瞬间 HTTP 请求数，也不是 Linux OS 进程总数。

快照中的七个活跃 CCI 控制器均报 active_local=16，合计 112 个 native task worker；本机受控实验另占 1 个已保留槽位。grader 的并发上限已包含在保留量里，不与这些 native worker 重复累加。

| 观测范围 | OS 可见进程 | 存活 | zombie | telemetry 距快照 |
|---|---:|---:|---:|---:|
| BC dsh | 57 | 57 | 0 | 3.6 s |
| BC hermes | 40 | 40 | 0 | 8.5 s |
| RQ3 0.0x | 40 | 40 | 0 | 5.8 s |
| RQ3 0.25x | 40 | 40 | 0 | 27.0 s |
| RQ3 0.5x | 40 | 40 | 0 | 2.3 s |
| RQ3 0.7x | 40 | 40 | 0 | 0.3 s |
| RQ3 0.75x | 40 | 40 | 0 | 0.2 s |
| 本机当前 PID namespace | 56 | 56 | 0 | 本次实时读取 |

七个活跃 CCI 的可见 OS 进程合计 **297**，加本机 **56**，本次覆盖范围合计 **353**。这些进程包含 supervisor、工具服务、观测器等；353 不表示 353 个并行模型请求。七个 CCI telemetry 均在 27 秒内且未发现 OOM kill。底层宿主机其他 PID namespace / 无关平台进程不在该观测范围，总数 **unknown**；`cgroup pids.current` 包含线程，不作为 OS 进程数相加。已停 CCI 的旧 telemetry 不计入当前合计。

## Search / fetch 与源码核验

两个 BC CCI 最近实际 handler preflight 分别于 06:48:51（Hermes）、06:49:52（DSH）通过 search 与 fetch。五个在跑 RQ3 CCI 的启动 preflight 均于 06:11 UTC 左右通过，配置 hash 与当前冻结配置一致。

额外只读抽查每个活跃 cell 的 3 个 slot、小型 `web.jsonl` 尾部：Hermes 与五档 RQ3 均见近期 search/fetch HTTP 200 且 success=true，样本内无失败；DSH 也见 search/fetch HTTP 200，原 schema 用 http_success=true。DSH 该 web ledger 不含事件时间戳，所以不虚构精确调用时间；preflight 时间独立有记录。这是样本与启动检查证据，不是对全历史工具调用零失败的断言。

实际使用 search `http://10.120.4.249:80/search`；fetch 入口是每台机器的 Reader 服务 `http://127.0.0.1:18080/fetch`。本次只读检查没有重新探测旧的 10.13.64.17:8080 或 10.120.7.221:8080，因此不据此声称这两个旧远端现在可用。

BC 冻结实现 338 文件、RQ3 319 文件、MMBC 318 文件逐一 SHA-256 核验，**无源码不匹配**。运行版本分别是 `bc-bounded-retry-v1`、`rq3-bounded-retry-controller-v1` 与对应 frozen worker；两个 harness 均走批准的 DeepSeek v4.1 Flash 1017 路由。信息损失 v2 冻结校验另见 completion audit。

## 证据路径

- 主快照（包含精确 controller、telemetry、readiness 路径和采样时间）：`outputs/preflight/bounded-resume-status-v1/20261110T065854Z.json`。
- 工具尾部样本：`outputs/preflight/bounded-resume-status-v1/runtime-web-tail-sample.json`。
- 预测：`outputs/campaigns/{bc-bounded-retry-v1,rq3-bounded-failure-retry-v1,mmbc-vera-bounded-retry-v1}/jobs/**/attempts/attempt_001/result.json`。
- 评分：对应 `outputs/grading/<campaign>/jobs/**/grade.json`；本页直接读逐条结果，避免把较旧的 `statistics.json` 当成最新状态。
- 调度：`outputs/cloud-runtime/bc-priority-ops-v1/status.json`；CCI 生命周期：`outputs/cloud-runtime/{bc-bounded-retry-v1,rq3-bounded-failure-retry-v1}/lifecycle/status.json`。
- 受控：`outputs/experiment3/controlled-native-bounded-v1/status.json` 与 `jobs/browsecomp_v3/q_001_r01/visual/compression-control.json`。
- 信息损失：`outputs/experiment6/bounded-window-five-arm-v2/{report.json,report.md,completion-audit.json}`。

## 快照之后的运行验证

BC 两个 harness 均持续保持16 active，控制器没有本地派发错误。Hermes 至少6条轨迹在第一次压缩后获得完整模型回复；DSH 的 q021/q025/q028 已将实际最终 wire 的图像 SHA、请求 ID 与 HTTP200完整回复及 raw usage 逐一绑定。DSH 这三次含8–10张独立小图，最长边不超过2033，均为high detail，缓存/非缓存/输出计数守恒。成功证明分页路径能工作，不表示连接错误全部消失。DSH q018/q019 的失败请求仍保留。证据：`outputs/preflight/bc-dsh-bounded-audit-v1/post-compression-success.json`。

受控校准的独立单次参数诊断已结束：在保持全部原生图、文本、工具和模型不变的前提下，调整了输出上限、tool choice 与 thinking；该请求上传阶段发生 WriteTimeout，客户端耗时300.241秒，未收到HTTP状态或usage。因此不能认定参数调整成功，也不能将失败归因为画布；当时尚未渲染。诊断费用/usage保留未知，没有自动重试。单独的原始请求代理路径诊断用于排查上传故障，其结果以对应独立诊断目录为准；不会改写已冻结受控结果。

07:10 UTC 补充：受控 MMBC pilot 的原图标定与带画布标定均返回成功。原图下界为4222 input tokens；后者保留2张原图并传入2页 .75画布，实测 cached4096 + non-cache1232 = input5328，output1、total5329，request2,591,992 bytes，guard通过；渲染5.560秒、编码0.629秒。真实 continuation 与三臂预算 gate 尚待验证，不能将这些校准值当成完整受控结果。首个 BC visual 已因连接故障失败，两文本臂没有可用目标而未运行；当时跨组 pilot handoff 因单组失败阻塞；下面的独立 v2 调度已移除这一不必要的跨组条件。

原始5,015,750-byte请求的单次代理路径诊断耗时120.849秒后 ReadTimeout，停在等待响应头阶段；没有HTTP状态或usage，未重试。代理未被证明能修复该问题，没有据此改写实验 spec。两次独立诊断的缺失 usage 与费用保持未知。

最终稳定代码检查：`python -m unittest discover -s tests -v`，727项全部通过（130.548秒）。后台 BC/RQ3 控制器、评分器及容量/CCI生命周期监督继续运行，诊断与测试进程均不占用额外长期实验并发。

07:20 UTC 运维更新：MMBC visual 的真实首次续答已报告 input5328，`passed=true`、原生图一致性通过；三臂组比较仍待文本两臂完成。已启动 `watch_controlled_bounded_pilot_v2.py`：等待 pilot 的六臂全部已知终态（含因 visual 失败而明确未运行的文本臂）、实际 worker 已回收且原协调器退出后，一次性续跑同一冻结计划的全部原40个可用组，仍限1 worker。每组自己的 visual target、±2%匹配及5%spread检查原样保留；单组API失败不再永久挡住无关组。失败/未知不会改成通过，既有尝试不重放，不替换问题。v1 已退出且无 full launch；v2 持有两代监督锁避免并存。新增7项调度测试通过，运行状态在 `outputs/experiment3/controlled-native-bounded-v1/pilot-full-handoff-v2/status.json`。
