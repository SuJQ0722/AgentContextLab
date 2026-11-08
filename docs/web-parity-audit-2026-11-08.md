# Hermes / DSH web 对照审计（2026-11-08）

**结论：DSH 复用了 Hermes 的 Serper 缓存代理与 Reader HTTP 协议，但没有完整复现 Hermes 的模型可见 web / vision 工具行为。** 当前真实测试支持“两个 harness 的搜索可用、结果一致且缓存命中”；不支持“fetch 可用”。实验保持暂停。本次只读审计未修改冻结实现、未调用模型、未恢复评测。

## 实测范围与当前状态

实际 provider 网络探测见 [端点记录](../outputs/web-endpoint-audit-2026-11-08/summary.json)（仓库实际位置 `outputs/web-endpoint-audit-2026-11-08/summary.json`）。这次 provider 探测由独立监督任务执行，不等于完整 agent loop 测试。

| 项目 | 实测结果 | 能得出的结论 |
|---|---|---|
| Serper `10.120.4.249:80/search` | Hermes、DSH 各 2 次；4/4 HTTP 200；每次 3 条非空结果；映射后的 URL/title/snippet 一致；4/4 `X-Cached: true` | 该固定查询在测量时可用，缓存确有命中；不能外推全 benchmark 命中率 |
| Serper 新查询交叉验证 | DSH 首次 HTTP 200 / `X-Cached: false` / 约 1.61 秒，随后 Hermes 同 query HTTP 200 / `X-Cached: true` / 约 0.284 秒；两次均 3 条非空且语义一致 | 同时证实该新查询的服务端 miss→hit 和跨 harness 缓存复用，不只命中旧缓存 |
| Reader `10.13.64.17:8080/fetch` | 两个 provider 分别请求 example.com 与历史失败 WordPress URL；4/4 在显式诊断 30 秒上限超时，未收到 HTTP 状态 | 在该诊断窗口未能取回正文；不是 DSH 单独失败 |
| Reader 真实 180 秒预算 | 独立 DSH example.com 调用于 04:38:58–04:41:58 UTC 运行 180.025 秒，TimeoutError，无 HTTP 响应 | 失败并非仅因诊断窗口降为 30 秒；根因仍未定位 |
| 优先 Reader `10.120.7.221:8080` | TCP connection refused；实际 DSH POST 04:39:47 UTC 返回 `ECONNREFUSED` | 本次不能作为可用替代 |
| Reader 网络层 | TCP 连接成功约 17 ms；禁用环境代理后的 `/health` 和 `/` 均 8 秒读取超时 | 端口接收连接不等于 HTTP 服务可用；未定位服务端/下游根因 |
| Reader 模式 | 本次加载的真实配置是 `extract_mode=text`；请求未带 LLM 字段 | 无 agent 模型推理；后端内部成本接口不暴露，不能承诺服务端零成本 |

原始 health 探测曾因环境 SOCKS 依赖缺失而本地报错，记录保留；上表使用后续直连探测，不把该本地 ImportError 误判为服务器异常。新增证据：[fresh DSH](../outputs/web-endpoint-audit-2026-11-08/fresh-search/dsh.json)、[fresh Hermes](../outputs/web-endpoint-audit-2026-11-08/fresh-search/hermes.json)、[180 秒 fetch](../outputs/web-endpoint-audit-2026-11-08/long-fetch.json)、[备用端点](../outputs/web-endpoint-audit-2026-11-08/backup-fetch.json)。历史 WordPress 失败来自 `outputs/campaigns/bc100-r3-all-strategies/jobs/hermes/summarize/q_034_r01/attempts/attempt_001/native/conversation.json`，当时也是 180 秒 timeout；同条轨迹中另一个 Wikipedia URL 被 Hermes SSRF 检查阻断，属于不同失败原因。

## 配置和请求协议

两者都经 [`scripts/local_web.py`](../scripts/local_web.py) 读取 Hermes local-web 配置，并用 `configs/experiment.json` 的 web 端点及环境变量覆盖。`FETCH_SERVER_URL` 可再次覆盖实验配置，因此运行时加载值是判定依据。优先端点 `10.120.7.221:8080` 只作为配置记录，当前 helper 不会自动探测或自动切换。

| 项目 | Hermes local-web | DSH local-web | 判断 |
|---|---|---|---|
| 搜索请求 | `POST http://host:port/search`；`X-API-KEY`；`q/location/gl/hl` | 同协议和字段 | 普通有效输入一致 |
| 查询语言 | 含任意 U+4E00–U+9FFF：China/cn/zh-cn，否则 United States/us/en | 同一 Unicode 区间与值 | 已用中英零网络 fixture 验证 payload 相等 |
| 搜索 timeout | httpx 30 秒，各网络阶段超时语义 | AbortSignal 30 秒墙钟截止，并合并工具取消 signal | 数值相同，超时语义不完全相同 |
| 缓存 | 请求同一代理；不自建客户端缓存 | 同一代理；不自建客户端缓存 | 缓存由服务端控制；JSON 序列化空格不同，服务端 cache key 实现未知 |
| Fetch 主体 | `url/extractMode`；无 query | 相同主字段；无 query | 同文本/markdown服务接口 |
| 可选密钥字段 | 空 `jina_api_key/llm_api_key` 省略 | 空值发送为空字符串 | 不完全相同，取决于服务器缺省值处理 |
| Markdown 模式 | 规范化 mode；缺 llm_base_url/model 在客户端返回错误；非空可选 key 才发送 | mode 不规范化；直接发送配置，缺字段交服务端处理 | markdown 可以涉及 Reader 后端 LLM；不是纯网页传输 |
| Fetch timeout | 配置默认 180 秒；httpx timeout | 配置默认 180 秒 AbortSignal；实际 BC overlay 外层 `fetchTimeoutMs=185000` | 不应误用 upstream tool 默认 30 秒描述本 campaign |
| Fetch 并发 | `extract(urls)` 每批 semaphore 默认 8；模型 wrapper 最多 5 URLs | 单 URL provider，没有该 semaphore；由工具/agent 并发调用 | 同一批页面的排队与延迟可能不同 |

## 模型可见行为的实质差异

| 项目 | Hermes | DSH |
|---|---|---|
| 搜索 schema | `web_search(query, limit)` 单查询；默认 5，limit 至少 1 | `web_search(queries)` 最多 4 查询并发；实际 BC 总结果 cap=5；多查询按排名交错合并、URL 去重；一个查询失败会取消整批 |
| 搜索返回 | JSON envelope：`success/data/web`，含 title/url/description/position | sources/snippet/truncated 转模型可读来源列表、外部内容提示及引用提示；没有 Hermes position/envelope |
| Fetch schema | `web_extract(urls, char_limit)`，最多 5 URLs；char_limit 范围 2,000–500,000 | `web_fetch(url)`，模型不能指定 char_limit |
| Fetch 返回 | JSON `results[{url,title,content,error}]`，title 固定空字符串 | `Fetched URL (HTTP status)`、外部内容提示、正文；status 是 **Reader 代理** 状态，不是源站状态 |
| 截断 | 默认正文 15,000 字符；约 75% 头 + 25% 尾，额外 footer；保存完整文本并提示 read_file；外层工具保留策略可能再次限制 | 实际 BC 上限 15,000 字符，含 URL/header/footer；只保留开头；provider 的 `truncated=false` 不代表最终显示未截断，tool 层会计算 effective truncation |
| URL 检查 | normalize、secret pattern/敏感 query 检查、DNS/IP SSRF 检查 | 本插件仅 HTTP(S) 与禁止 URL userinfo；`ctx.web.fetch` 直接委派，不补上 Hermes 的 DNS/secret 检查 |
| 页面内 base64 | wrapper 转 placeholder/link，最后对 JSON 再清理 | 插件与所用 text renderer 无该清理；收到内嵌 base64 可进入正文并消耗字符预算 |
| Fetch 错误 | per-URL 错误 envelope，保留服务端 error/detail/message，其他 URL 可成功 | 抛异常；HTTP 错误只保留状态，`success=false` 给通用错误；上层工具处理异常 |
| Fetch 成功条件 | `success` 必须 truthy；data 转字符串，空值转空正文 | 仅 `success === false` 拒绝；缺 success 但 string data 接受；非 string data 拒绝 |
| Search 异常响应 | 缺 organic 当空结果；过滤非 dict 条目 | 缺/非数组 organic 抛错；未做 Hermes 的逐项类型过滤 |

因此，相同网页内容可能在两者留下不同尾部证据、不同 token 数、不同错误信息和不同搜索调用次数。当前结果可称“共享检索后端的两种 harness”，不能称“web 工具完全一致的受控替换”。完整文本保存提示也不保证当前仅 web 工具集能调用 read_file。

## Vision 工具与图像输入

`plugins/dsh-local-web/index.mjs` 在 agent/pre-step 显式限制可用工具为 `web_search`、`web_fetch`。该插件没有 `vision_analyze/image_search/image_crop/image_zoom_in`。Hermes 仓库有这些工具，实验 3 的 capture runner 显式注册并检查它们；原 BC Hermes worker 自身使用 `enabled_toolsets=['web']`，也不能把整个 Hermes 仓库支持的 vision 工具当作该 BC 轨迹已经启用。

DSH 的 `dsh-evaluation` 可以附加题目原图，`dsh-context` 可以附加压缩 canvas；**图像作为模型输入**与**具备图搜/crop/zoom 工具**是两项能力。已有图像 wire 审计也不证明上述工具已复现。完整多模态任务的工具公平性仍需独立处理。

## 可观测性与零网络验证

- 两侧 `web.jsonl` 都记录 `X-Cached`、代理 HTTP 状态、客户端请求耗时；源站状态为 unknown。缺失缓存头不能计作 cache miss；web cache 与模型 cached input 不是同一指标。
- Hermes frozen Recorder 的 `success` 表示 HTTP<400；DSH 的 success 在解析 JSON/检查显式 success=false 后才为 true，但在后续 organic/data schema 检验之前已记 true。因此两列不能直接合并为“工具成功率”。
- DSH 这份指标没有 error_type；Hermes transport Recorder 有 error_type。两者均不报告 Reader 内部 Jina/LLM 耗时、token 或缓存命中，客户端 HTTP 时间不是模型 API 延迟。
- 零网络 provider fixture 已执行 4 项断言，输出 `outputs/web-parity-audit-2026-11-08/provider-fixture.json`：中英文搜索 payload 相同、正常文本返回语义相同、缺 success 与非字符串 data 两个差异可复现。真实 transport 全部替换，无网络请求。第一次用系统 Node 12 无法加载现代模块，使用仓库固定 Node 24 后通过；未改实现。
- `scripts/local_web.py::validate_web` 只检查有 sources / 非空正文，不能排除 HTTP 200 中嵌入错误页，也不检查完整模型工具 schema。这不是完整 parity gate。

源码依据：[Hermes search](../hermes-agent/plugins/local_web/search_provider.py)、[Hermes fetch](../hermes-agent/plugins/local_web/fetch_provider.py)、[Hermes wrapper](../hermes-agent/plugins/local_web/__init__.py)、[DSH adapter](../plugins/dsh-local-web/index.mjs)、[DSH tool layer](../deepseekHarness/packages/web/tool-web/src/index.ts)、[BC overlay](../scripts/run_dsh_eval.py)。本次未修改这些文件。

## 恢复前需要解决的事项

1. 先让 Reader 对正常页面和历史失败页面在真实预算内返回非空有效正文；TCP 通不能作为恢复依据。不得用搜索成功掩盖 fetch 失败。
2. 如果要求工具层复现，应另建版本对齐单/多查询、结果 envelope、头尾截断、base64 清理、URL 检查、错误与 success 计数；保留旧实验定义与结果，不能静默覆写。
3. 多模态实验需要另行明确 DSH 图搜/crop/zoom 能力；文本检索协议一致不构成该能力验收。

这三项是当前证据支持的后续工作，不是已完成修复或恢复运行的声明。
