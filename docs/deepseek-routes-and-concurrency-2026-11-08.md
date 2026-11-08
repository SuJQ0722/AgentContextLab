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

## 并发与实验定义

核心实验为两个 harness（Hermes、DSH）× 五种策略（No Compression、Summarization、Sliding Window、Discard-All、Visual Rendering），BC100 × avg@3，共 3,000 条计划轨迹。目标为每云单元 16 个题目任务，10 个单元合计 160，加本机 2 共 162。题目任务数量不等于操作系统 PID 数量，也不等于每分钟 API 请求数。

旧控制器已停止领取新题，仅让在途轨迹自然收尾，未向原生模型进程发送终止信号。新云代为 ops5，使用原来的 8 核 32 GiB、afs_agents、私有镜像与 workspace，只显式更换 routes1 bootstrap。先单个单元 16 并发验证，再决定其余单元是否具备扩展条件；配置目标不代表已经有 162 个任务运行。

冻结的原始 plan、config、spec、cohort 与历史结果不改。`route-plan-v1.json` 将同一 `(question_id, repeat)` 在全部十个单元固定为同一渠道；已有任意 claim 的 119 对保留原渠道，完全未领取的 181 对分配为 sfb 61 对、两条 sfc 各 60 对。因为 sfc 大图验证失败，对应 1,200 条计划任务暂不派发；不会改用另一个渠道后伪装成同一批数据。历史超时/错误不会自动重跑。

route plan SHA256：`79268981295a292896c320e6447b010ce5ca390908f93019413ea8d321e314e4`。

新入口先通过原始配置与源码验证，再生成仅 model/config 指针变化的 runtime 输入；claim、lineage、请求边界和实际响应分别记录渠道。DSH 原始 usage observer 仍为唯一计数来源，新增 returned-model sidecar 通过 request_id 关联，不重复累计 token；Hermes 保留原 SDK/HTTP/辅助请求 guard。

成本按 cached input、non-cache input、output、total 分列，缺失值保留 unknown。TokenHub 实际美元价格尚未验证，不套用 Gemini 价格。端到端与客户端 API 耗时可测，provider 内部耗时未知。最终分析应按实际渠道分层，并保持同题配对。
