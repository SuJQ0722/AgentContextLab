# DeepSeek 同版本渠道与并发调整（2026-11-08）

TokenHub `/models` 实测返回 218 个模型条目，其中以下四个请求名指向同一 `deepseek-v4.1-flash-1017` 版本标识。不同渠道名不证明独立配额、相同权重或相同计费。

| 完整模型请求名 | 小图 + 工具往返 | 原始 8 张压缩图（37,286,868 base64 bytes） | 当前派题设置 |
|---|---|---|---|
| `deepseek-v4.1-flash-1017/huoshan/huoshan` | 历史主渠道 | 历史 q062 HTTP 200；另有 RPM/TPM 与内存限制 | 每云单元 1 |
| `deepseek-v4.1-flash-1017/zijian/sfb` | HTTP 200，颜色与工具结果正确 | 串行直连、代理均 HTTP 200 | 每云单元最多 15；本机合计最多 2 |
| `deepseek-v4.1-flash-1017/huoshan/sfc` | HTTP 200，颜色与工具结果正确 | 串行直连、代理均 HTTP 429 `system_memory_limit` | 0，等待进一步验证 |
| `deepseek-v4.1-flash-1017/zijian/sfc` | HTTP 200，颜色与工具结果正确 | 串行直连 HTTP 429 `system_memory_limit` | 0，等待进一步验证 |

成功探针返回的模型名称为 `deepseek-v4-1-flash-261017`。大图探针逐项保留原始 PNG 的顺序、SHA256、尺寸和 detail，未重新编码、缩放或删除图像；HTTP 200 仅证明传输接受，不证明全部图像的语义理解或 benchmark 准确率。

最初三个并发直连大图请求均出现 90 秒 WriteTimeout；随后同一 sfb 请求串行直连也成功，因此不能把原因唯一归为直连不可用。现保留原模型网络路径。两条 sfc 的后续失败则明确发生于上传完成后，返回网关内存保护错误；其限制作用域未知。

证据：`outputs/preflight/tokenhub-routes-20261108T110747Z/` 中的 `routes.json`、`capability/`、`large-canvas/`、`large-upload-network/summary.json`。这批工程探针不计入 benchmark 准确率，真实成本独立保留；失败且没有 usage 的调用记为 unknown。

## 并发与实验定义（初始 routes1）

核心实验为两个 harness（Hermes、DSH）× 五种策略（No Compression、Summarization、Sliding Window、Discard-All、Visual Rendering），BC100 × avg@3，共 3,000 条计划轨迹。目标为每云单元 16 个题目任务，10 个单元合计 160，加本机 2 共 162。题目任务数量不等于操作系统 PID 数量，也不等于每分钟 API 请求数。

旧控制器已停止领取新题，仅让在途轨迹自然收尾，未向原生模型进程发送终止信号。新云代为 ops5，使用原来的 8 核 32 GiB、afs_agents、私有镜像与 workspace，只显式更换 routes1 bootstrap。先单个单元 16 并发验证，再决定其余单元是否具备扩展条件；配置目标不代表已经有 162 个任务运行。

冻结的原始 plan、config、spec、cohort 与历史结果不改。`route-plan-v1.json` 将同一 `(question_id, repeat)` 在全部十个单元固定为同一渠道；已有任意 claim 的 119 对保留原渠道，完全未领取的 181 对分配为 sfb 61 对、两条 sfc 各 60 对。因为 sfc 大图验证失败，对应 1,200 条计划任务暂不派发；不会改用另一个渠道后伪装成同一批数据。历史超时/错误不会自动重跑。

route plan SHA256：`79268981295a292896c320e6447b010ce5ca390908f93019413ea8d321e314e4`。

新入口先通过原始配置与源码验证，再生成仅 model/config 指针变化的 runtime 输入；claim、lineage、请求边界和实际响应分别记录渠道。DSH 原始 usage observer 仍为唯一计数来源，新增 returned-model sidecar 通过 request_id 关联，不重复累计 token；Hermes 保留原 SDK/HTTP/辅助请求 guard。

成本按 cached input、non-cache input、output、total 分列，缺失值保留 unknown。TokenHub 实际美元价格尚未验证，不套用 Gemini 价格。端到端与客户端 API 耗时可测，provider 内部耗时未知。最终分析应按实际渠道分层，并保持同题配对。

## 更新：routes2 显式修订与扩容

16-trial Hermes visual 原生 canary 已验证：首批16条均启动，155次已完成API记录无SDK错误，28次压缩后请求/56张图像完整性通过；已完成调用 cached 1,650,688 + non-cache 836,758 + output 164,167 = total 2,651,613，字段完整且守恒。此快照并非完整成本或准确率。随后8.23分钟独立窗口，sfb每分钟16.03次实际HTTP发送、128次SDK成功返回；窗口前开始的请求可能在窗口内完成，发送数与完成数不可混用。

确认两sfc暂不适合真实大图后，创建独立 `route-plan-v2.json`，而非覆盖v1。全部49历史controller都有停派快照或本机精确进程身份已退出的证明；迁移时120个受影响pair没有任何claim或attempt。因此这120对只从sfc改到已通过验证的sfb，既有119对原route和61对sfb保持不变。新的分配为原route119对、sfb181对；没有因sfc预分配而长期搁置的1,200条任务。

v2 SHA256：`2ab0bcf2d3c745909ebfa9e72751e29de71b10ed1353aa7e0695c38a6c7c8153`。父v1 SHA及binding原样保留；已有v1数据仍记v1 lineage，新数据记v2。受影响pair已有任何历史claim则修订会拒绝；同route父代尚未完成runtime准备时，新同题任务会暂缓，避免跨代竞态。

其余9个云单元的ops5创建已返回submitted，使用routes2入口，每单元目标16。Hermes visual canary自然收尾后，由独立watcher在ACP SUCCEEDED与clean drain都确认后创建ops6，同样16；不会中断其在途题目。原本机池已完全退出，新的本机routes2池目标2，支持DSH visual，共用永久claim与每cell32硬槽。目标总数160+2=162；submitted、supervisor启动、native启动、真实API成功是不同阶段，实时数以监控为准。

代码检查：根目录261项unittest通过，另5项Node归因/图像guard测试通过。镜像、8核32GiB规格、afs_agents和workspace路径保持不变。实际云端计量与稳定窗口仍需持续监测。

## 更新：共享目录发布竞态与安全续跑（io3）

大规模派题实测暴露共享AFS的短暂可见性窗口：claim目录可见时，其owner.json尚未可读。四个旧调度器因此退出，并非模型限流。新io3独立入口只对该明确情况等待/暂缓派题；冲突或损坏的owner仍拒绝。其他调度异常会停止新增派题，并等待已经跟踪的原生子任务自然结束，避免控制器异常连带终止付费轨迹。

四个ACP FAILED节点已核官方终态、节点UID、boot、namespace与exit证据。只批准30条完全没有worker-started、command、native、API或terminal证据的旧claim续跑：DSH摘要15、Hermes摘要6、Hermes窗口6、Hermes丢弃3。原spec、claim、slot与原worker-started独占保护不变，恢复与新pending共用16并发及1/15路由配额。Hermes丢弃另7条已启动但无结果轨迹保留unknown/interrupted及已发生费用，不自动重跑。

DSH另发现前导连字符题文被CLI当作参数：独立新入口在原始题目前插入参数终止符 `--`，所有permission/patch参数仍在其前，题文逐字节保持不变。实际两层CLI解析离线验证通过；旧q043失败结果未覆盖或重跑。

新的ops6使用io3 bootstrap，6个具备终态证明的节点已提交，剩余4个旧DSH节点等待自然收尾后按相同规格替换。每节点16、本机2的目标不变；此时仍处替换阶段，不将submitted误称为162实际运行。原v1/v2冻结源码没有修改，维护代码来源与哈希写独立sidecar。

最新根目录检查289项通过（包含部署证据链检查）；四份真实恢复manifest逐条校验通过。记录目录为 `outputs/cloud-runtime/io3-recovery/`。新流量的持续稳定性仍以实时监测为准；gateway `system_memory_limit` 的作用域和实际美元价格仍未知。

## 全节点运行验收：2026-11-08 12:49 UTC / 北京时间20:49

10/10新云节点及本机均运行；最后启动节点已观察至少5分钟真实调用，早批节点观察超过十分钟。配置为每云cell16、本机2，共162个题目任务槽位。以下为同一轮独立采样的实测进程数，任务完成与初始化时会短暂低于目标；所有controller仍正常补位或满额，没有stop/deferred/OOM。

| 策略 | Hermes目标 / trial / native | DSH目标 / trial / native |
|---|---:|---:|
| No Compression | 16 / 12 / 11 | 16 / 16 / 16 |
| Summarization | 16 / 15 / 14 | 16 / 14 / 13 |
| Sliding Window | 16 / 16 / 16 | 16 / 16 / 16 |
| Discard-All | 16 / 14 / 13 | 16 / 12 / 12 |
| Visual Rendering | 16 / 16 / 16 | 16 / 16 / 16 |
| 本机辅助DSH Visual | — | 2 / 2 / 2 |
| 全部合计 | 目标162 / 实际trial149 / native145 | 含本机 |

native按Hermes Python与DSH Node计数；75个DSH Python launcher另列，不重复视为模型执行引擎。11个namespace实测OS活跃PID共511，不能把162个题目任务槽位当作全部系统进程数。

最终五分钟窗口12:44:19–12:49:19 UTC：1,362个SDK返回中5个失败（约0.37%），分别为3次网关system_memory_limit和2次连接/传输错误，未把HTTP状态再次重复计入SDK失败。没有新增ModelAccount RPM/TPM限流证据；上游memory保护仍偶发，不能声称完全无错误或四渠道有独立配额。DSH visual q060的memory429原生重试在审计截止时仍在途；不提前记为成功。

所有已知raw token守恒检查通过，窗口9条usage未知保留unknown；美元成本缺可核实的实际渠道价格。新IO3 Hermes的199次压缩canvas请求无缺图/像素校验失败，DSH图像guard未报错。原生completed不代表答案正确，准确率仍待评分。

30条明确从未启动的claim已全部续跑：每题单一worker-started/native，原spec/claim及启动前slot SHA匹配授权。恢复审计截止14 completed、0 failed；另7条已启动但中断的Hermes discard轨迹保留unknown与原费用，不自动重跑或覆盖。

正式证据：campaign `monitor/fleet-io3-load-final-20261108T1249Z.json`、`fleet-io3-health-final-20261108T1249Z.json`、`final-io3-processes-final-20261108T1249Z.json`，以及 `outputs/preflight/io3-recovery-live-audit-20261108/` 与 `io3-last4-flow-audit-20261108/`。所有10个ops6创建回执成功后，provisioning watcher已停止；实验controller、成本监控与ETA只读observer继续运行。由于两条有效路由配额为1/15且仍缺充分分路由尾部校准，旧单渠道完工日期估算已失效，当前不提供伪精确完工日期。
