# Hermes 原生图像路由修复与真实验证

结论：**新版本的图像传输链已通过验证；原语义 probe 存在来源及乘客/全体人员口径歧义，不能用于判定视觉识别是否通过，仍不能宣称视觉压缩整体没有问题。** 没有重启批量任务，也没有改写旧冻结实验。

## 修复范围

新增 `scripts/hermes_native_vision_worker_v2.py`，包装原 Hermes worker，在正常配置加载前明确设置 `model.supports_vision=true`、`agent.image_input_mode=native`。同步/异步辅助 caption 调用被禁止，异模型请求也被禁止。旧 `hermes_bc_worker.py`、核心冻结实现与 plan 均未修改。

每次真实 `VisualEngine.compress` 返回后记录图像 payload SHA256、解码 pixel SHA256、尺寸、mode、detail，并对应保存的渲染 PNG。随后在正常 Hermes 路由后的 Completions 参数及 `httpx.Client.send` 最终 JSON 中分别验证所需图像的数量、像素和 detail；缺图或改变则 fail closed。代码没有在最终 SDK 请求中补塞图片。PNG 无损重编码可以保持 pixel hash，但 detail 不可改变；重复图像的数量也计入核验。

`--rq3-pdf` 可组合已验证的有界内存 PDF 适配。此功能只为新的版本化 worker 提供，不修改旧 RQ3 任务或静默恢复旧队列。

## 测试与真实调用

最终零 API fixture：`outputs/preflight/hermes-native-vision-v2-1794068477201776477/result.json`。真实 Hermes 工具循环因历史增长触发压缩，随后经过真实模型路由发送图像；SDK 和最终 HTTP 均与 renderer 像素一致。该测试未 mock 模型视觉能力判定，也未绕过路由补图。两个 ledger 单测覆盖无损 PNG 编码、detail、重复图像数量和 URL-only 图片拒绝。

付费语义 probe 均使用同一个 DeepSeek 路由和上述新 worker：从旧 BC q003 的真实 32,948-token 请求提取原文，分别用真实 VisualEngine 压缩一个原文短片段与完整历史，再经原生路由发送。这里只显式触发单次压缩来审计传输/读取，不是新的 benchmark accuracy。原文历史文本不发送给模型作答，只发送压缩后的 canvas 与不含参考答案的问题。短片段不替代完整历史结果。

| 真实 probe | Canvas 数 | 最终 HTTP 像素/detail | 返回三数字 | 原参考数字字面匹配（非有效语义验收） | input / cached / output / total |
|---|---:|---|---|---:|---|
| 真实源短片段 | 1 | 一致 | 179 / 93 / 86 | 3/3 | 2188 / 0 / 457 / 2645 |
| 完整真实历史 | 3 | 一致 | 186 / 65 / 121 | 0/3 | 3283 / 0 / 2065 / 5348 |

短片段回答还引用了图中的 Colonist 报纸，并说明 179/93/86 是乘客口径、另有船员死亡。完整历史回答则选择了不同数字并给出可疑日期；在含 Wairarapa 的原始工具正文中未找到 186 或 121，而 65 出现为 crew 数。完整历史包含多个来源，问题的来源定位也有歧义，因此不能仅用这个 probe 区分视觉辨认、跨来源选择与幻觉，但**它既不能证明完整视觉历史能被可靠读取，也不能单凭原参考不匹配证明视觉识别失真**。

两次实际调用都未使用 web，HTTP 模型调用各最多 1 次。短/完整 probe 的客户端 SDK 时间分别为 7.14 / 170.63 秒；端到端 agent loop 分别为 17.22 / 188.09 秒，均不称 provider 内部处理时间。总已知 token 为 7,993；image-token 细分与实际美元账单未提供，保持未知。

首批 probe 曾在本地压缩入口因不支持 `force` 参数而退出，发生于任何 SDK/HTTP 模型调用之前；原 attempt 保留。修正调用接口后使用新的 `short-attempt2` / `full-attempt2` 目录，没有覆盖失败记录。参考答案只用于本地评分；发送文本中不含 179/93 及其事实关系，系统主机架构字符串 `x86_64` 中的 86 不是答案提示。

## 证据与剩余问题

- `outputs/preflight/hermes-native-wire-probes-v2/evidence-report.json` 汇总模型回答、usage、SDK/HTTP 图像账本。
- 各 attempt 的 `native/metrics/vision-route.jsonl`、`vision-wire.jsonl`、`vision-render-sources.jsonl`、`calls.jsonl` 和完整 request/response gzip 保留审计链。
- `source-provenance.json` 标记原轨迹和 call_id；短片段、完整源各自保存，未用合成红蓝图替代真实压缩证据。

后续应将“图像是否真正发送”与“完整压缩历史是否准确保留事实”分开报告。后者仍需严格的来源定位 probe、key-fact recall 与分辨率/密度实验。若改变画布尺寸、字体、分辨率或模型，需要新的版本与独立结果，不能将本次完整历史失败改写为通过。

## 原题歧义核查及独立 v3

原题只问 Wairarapa 的 “total number of people on board / saved / drowned”，没有指定来源日期，也没有明确只问 passengers。第 24 条原始工具正文的 Colonist 26 November 1894 段落写的是 passengers 179、其中 saved 93、drowned 86，紧接着另报 crew 死亡 20、总死亡 106。短片段读取了这三个数字，但它追加的总人数推断也不能视为有充分依据。上述 3/3、0/3 只保留为旧参考的字面匹配，不能当作有效语义验收分数；没有修改既有问题、响应或评分记录。

完整回答声称来自 Wikipedia 的 186/65/121，在该存档 Wikipedia 工具正文中缺乏相应计数支持；原文日期为 24 October 出发、29 October 失事，响应却写 June/August。另一 DOC 来源的 65 是 crew 人数。这里能确认引用/来源选择存在问题，但不能隔离其由读图、跨来源整合还是先验幻觉造成。

经单独授权，新增 `full-explicit-source-v3`：保持原完整 3 张 canvas 与既有路由，只将问题明确定位到 Colonist 26 November 1894，并明确询问 PASSENGERS 及其中 saved/drowned，不含参考答案，不含船员、不允许换来源或使用 web。新 probe 最多 1 次 HTTP 模型调用；它是独立结果，不覆盖原题。切图仅作为离线候选，此处没有启用切图或新的生产布局。

独立 v3 已结束：最终 HTTP 与旧 full probe 的 3 张图连 payload SHA 都逐张相同，像素/detail 核验通过。provider 返回 `finish_reason=length`、input 3,329、cached 384、output 4,096（全部为 reasoning）、total 7,425，未产生最终答案。单请求上限阻止了自动付费续接，Hermes 最终记录 native_error。客户端 SDK 150.23 秒、agent loop 180.31 秒。**这是输出预算耗尽导致的语义验收未完成，不是 HTTP 超时，也不是“图像看不懂”的实验证明**；未答不记为三个事实均答错。没有切图复测或额外续跑。

三次实际模型 HTTP 调用累计已知 input 8,800（cached 384、non-cache 8,416）、output 6,618、total 15,418。完整 probe 的未决问题需在明确预算的新验收中继续，或由人工图像审阅补充；本轮传输修复成立，语义可靠性仍不作通过承诺。

## 最后一次正式输出预算验收（8192）

经独立授权，`full-explicit-source-v4-output8192` 保持明确来源的同一个问题和原完整 3 张图，将实际 request 的 max_tokens 从独立 probe 的 4,096 对齐到正式实验的 **8,192**；只允许一次 HTTP 模型调用，supervisor 硬上限 360 秒，未追加调用或启用切图。最终 wire payload SHA、pixel SHA、detail 逐张与原 full 图一致。

结果仍未产生最终答案：provider 正常返回 `finish_reason=length`，input 3,332、cached 0、output 8,192（全部 reasoning）、total 11,524。没有网络错误，也没有触发 360 秒超时。SDK 144.09 秒、agent loop 176.58 秒；单次调用上限阻止了 Hermes 自动续接，因此最终 native-result 为 failed/空答案。**传输链通过不等于语义答对；完整图在本次 8,192 输出、单请求验收中仍无可评分答案，语义可靠性不能宣布通过。** 这不等于证明模型没有多模态能力，也不代表允许多轮续接的完整 benchmark 必定失败。此次后不再增加预算或追加付费。

所有四次实际模型 HTTP 调用均有完整 provider usage：input **12,132**（cached **384**、non-cache **11,748**），output **14,810**，total **26,942**。缺失 usage 为 0；图像 token 细分与实际美元仍未知。原本地 TypeError 的两个 attempt 均发生于调用前，0 模型 HTTP 请求。四次 probe 属于诊断开销，不能混进正式 benchmark 准确率或生产缓存命中率表。

最终证据汇总仍在 `outputs/preflight/hermes-native-wire-probes-v2/evidence-report.json`。路由 wrapper、fixture 和 tests 已冻结，未修改 Hermes 源码、旧 worker、核心冻结实现或 plan；没有恢复批量实验。
