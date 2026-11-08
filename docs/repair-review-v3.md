# Hermes / DSH 修复验收（v3，实验暂停）

本轮只修复代码、检查真实 web 服务和运行 localhost 模型 fixture；未恢复付费模型评测，未创建 SCO 实例。用户要求先 push `dev`，查看图像与部署方案，再决定开始实验。所有旧 STOP 和 `outputs/PAUSED_BY_USER.json` 保留。

## 图像与表格

新版共享 Hermes renderer `multimodal-wrap-v2` 支持位于压缩范围内的 inline data URL、本地图片、搜索结果缩略图，以及 crop/zoom **实际返回的图片**。不再从 assistant 参数拿父图冒充裁剪结果，不再静默只取前两张图。相同消息内的同像素图片可去重绘制，但每次来源出现仍记录；不可读图片显式失败。表格保留完整单元格与行数，不再截到 15/30 行。

DSH 视觉策略将图片放回原消息附近，复用同一渲染器做文字环绕，不再用占位符替代图片后把原图追加在末尾。独立的 summary/native 与 window/native 控制策略不能被此行为替代。

可直接查看的文件：

- **同一输入的对照：[Hermes](visual-integrity/repair-v3/hermes-matched.png) / [DSH](visual-integrity/repair-v3/dsh-matched.png)**。两条实际路径输出的 PNG 字节相同，证据见 [matched-canvas-manifest.json](visual-integrity/repair-v3/matched-canvas-manifest.json)；DSH 同时经过原生持久化替换与 pi-ai 最终 HTTP 序列化。包含原图、实际 crop/zoom、四个搜索缩略图、完整表格。
- [Hermes：原图、crop、zoom、四张搜索结果图和完整表格](visual-integrity/repair-v3/hermes-all-evidence.png)。这是 synthetic fixture；调用真实 crop/zoom handler，搜索 transport 为本地桩，**不冒充真实网络图搜**。
- [DSH：原生 agent 压缩后的第一张画布](visual-integrity/repair-v3/dsh-native-compaction-first-canvas.png)。这是工具链验收，输入为长文本画布，所以缩略图文字很小；不据此声称模型读懂了内容。

后两张不同输入的预览仅展示各自工具链；逐像素/字节相同的结论只来自第一行同输入配对，不能推广成不同实际轨迹会产生相同画布。

DSH 的 attachment 与 provider image profile 现在显式保留原 PNG；5 张完整画布的 source → native attachment → 最终 HTTP image bytes 全部匹配。没有用 tiling 偷换布局。64MP/50MiB 是本地单图 admission ceiling，20MiB aggregate request guard 仍保留；超过上限失败，不静默缩图。这不保证远端模型接受任何尺寸。画布排版时将证据图缩成缩略图，是共同 renderer 的行为；发送画布保持字节不变不代表源照片没有经历版面缩放。

DSH 原 adapter 会省略 Hermes 指定的 image `detail`。v3 显式保留每张图的 low/high/auto，并在传输适配层仅补齐这个字段；随后检查图片数量、顺序、SHA 和 detail。它是有记录的修复层，不伪称纯观察器。最新同输入 fixture 同时验证 PNG 字节、detail 及原生会话重放一致。

新版 Hermes 实际 agent loop 的 localhost fixture 已执行 `image_crop`、`image_zoom_in`、`web_search`，随后真实自动压缩；模型看到五个指定工具，最终 HTTP 中图像像素匹配。原始输入图片也进入第一轮原生请求。真实 DeepSeek 对完整画布的语义理解不由 localhost fixture 证明，本轮没有调用它进行新评测。

## 压缩策略和工具

`shared_context_policy.py` 直接调用 Hermes 的 none / discard / sliding_window / summarize / visual 引擎。配置、阈值、保留规则及摘要 prompt 来自共同入口。DSH 摘要请求由其受监控的原生 LLM 客户端执行，再把实际响应交给同一 Hermes 引擎组装；Python bridge 自身不调用模型。

新的 DSH `hermes-policy-v3.mjs` 保留多角色消息的 durable surface replacement，旧 `index.mjs` 仅作为历史/独立 native 控制实现保留。同输入五策略两次压缩和新进程恢复的 Python 对照已通过；DSH 的原生 journal/replay 也在独立同输入集成 fixture 中验证通过，见配对画布 manifest。

**明确的协议变更：**新核心比较使用 Hermes 原生行为，取消旧 DSH 独有的本地估计 16k post-compression 硬拒绝；触发来源改为已返回的 provider prompt usage（含 cache）。保留本地 token 估计用于观测。受控 baseline 仍须独立匹配 post-compression/image token budget，本轮策略对齐不表示它的预算 gate 已通过。旧历史结果不得混入此新版本。DSH CLI 的 `sliding_window_native` / `visual_native` 在新核心入口是历史参数别名，manifest 同时保存 canonical `sliding_window` / `visual`；不是受控 native-image baseline。

两个新入口均使用同名五工具：`web_search`、`web_extract`、`image_search`、`image_crop`、`image_zoom_in`。DSH 直接桥接真实 Hermes handlers，复用文本 spill 与 aggregate-budget helper；图像 attachment 入库前后逐张校验。DSH schema vocabulary 和 harness 原生 message framing 仍有差异，不能宣称整个 harness 字节相同。详见 [工具对齐与实测](hermes-dsh-tools-v2.md)。

工具限制提前到 DSH `agent/created`：此前在 `pre-step` 限制会让第一条 HTTP 请求仍列出 28 个工具，新入口必须从第一条请求起就只有这五个。还修复了 DSH 追加 `[::1]` 的 `NO_PROXY` 值继承到 Python/httpx 后导致的端口解析错误。两项都来自实际生产入口的 localhost 验收，而非仅检查配置文件。

## Web 服务和剩余外部条件

| 项目 | 实测/状态 |
|---|---|
| 缓存 Serper 文本搜索 | 非空结果可用；此前 miss → 跨 harness hit 对照通过 |
| Serper Lens 公开图 URL | 真实请求成功，三条非空结果 |
| `10.13.64.17:8080` | 仍超时，**没有声称修复远端服务器** |
| 新本地同源 Reader | `127.0.0.1:18080`，真实 example.com 与历史失败 WordPress 页均 HTTP 200、非空；实际 Hermes wrapper 也通过 |
| Fetch 缓存 | 同 URL 实测 `X-Cached: false → true`，正文 SHA 一致；来自实际 cache lookup，Jina/无字段/失败保持 unknown |
| 本地图/crop 的反向图搜 | 已找到旧 Hermes `.env.local` 的 imgBB key，单项迁入当前私有配置并由两 harness 共用；真实合成 crop 上传与 Lens 调用成功，上传 SHA 与 crop 一致，合成图匹配数为 0 |
| SCO | 已记录 `afs_agents`、私有镜像选择 `ccr-zuhu2026 / sjq-dev-cpu`、当前项目工作目录；仍缺 active profile，镜像 tag/完整 URI 与云资源 ID 待查询；没有创建实例 |

Reader 仅启用 text 模式并拒绝 LLM 字段。它读取固定 SHA 的共享 ReaderEngine，不读取源码所有者的配置/凭据；未来每台实例需自己的 loopback 服务。新配置显式选择该 endpoint，旧历史配置不变。对从公开 URL 下载且 SHA 匹配的原图，两入口使用相同 origin ledger，可直接将其公共原始 URL 交给 Lens；**不能把 crop/zoom 图替换成父图来绕过上传缺失**。

## 待用户验收的运行入口

- [实验配置](../configs/experiment.v3.review.json)，`review_approved=false`。
- [Hermes worker](../scripts/hermes_bc_worker_v3.py) 与 [DSH worker](../scripts/run_dsh_eval_v3.py)：默认 dry-run；暂停 marker 与版本边界在任何付费调用前检查。已有 attempt 不覆盖，不自动重发未知调用。
- [SCO 部署清单](sco-review-plan.md)：核心 10 台，每台 8 核/32 GiB/32 worker；所有条件组展开最多 22 台/704 worker，需先对齐总规模。尚未实现/验收跨主机分片锁的正式云调度，不应直接复用单机 PID 恢复逻辑。

原始 cached/non-cache/output usage、缺失计数、摘要辅助调用、渲染时间、web cache header 与 HTTP 图像 ledger 继续分别保存；CLI 总时长不当作 provider 延迟。任何费用/准确率结果都不能从这些零模型 fixture 推算。

旧 DSH SDK 会把未返回的 cache counter 先填为零，再省略零字段；因此**只有 normalized usage 的历史记录不能证明 cache=0**。新版增加原始 HTTP JSON/SSE usage 观察器，保存字段是否存在、已知小计和守恒检查，缺失保持 null，并在调用结束刷新日志。原始请求/响应 token、web 缓存和渲染 token 估计分开；详见 [计量说明](shared-usage-accounting-v3.md)。

2026-11-08 的只读 `GET /models` 返回 HTTP 200，仍包含精确 route `deepseek-v4.1-flash-1017/huoshan/huoshan`；返回记录没有提供 modality 字段。这是目录可用性检查，不是新推理或视觉理解评测。

## 最终回归与入口验收

- Root unittest：102 项通过；使用项目 DSH 环境的 Node 测试：36 项通过。
- Hermes 官方测试入口：原生视觉证据 10 项、表格渲染及 Markdown 表格 21 项通过。
- Hermes 实际 agent loop 和摘要 SDK/HTTP 路由 localhost 验收通过，包括错误模型、endpoint 和异步绕行的拒绝检查。
- [DSH 正式新入口验收](visual-integrity/repair-v3/dsh-entry-validation.json)：`none`、`visual_native` 各 5 次 localhost 模型请求，第一轮起均只有指定五工具；实际执行 search/fetch/crop/zoom，40k synthetic provider usage 触发真实共享压缩。新画布全部进入最终 HTTP，SHA 与 image detail 一致；测试前后实现文件 hash 相同。

这些检查不产生付费模型调用，不提供 benchmark accuracy 或真实模型视觉理解结论。所有实验仍暂停；正式 SCO 分布式运行仍待部署参数、分片恢复验收及用户检查。

## 文件读取隔离（用户追加要求）

模型仅能调用五个 web/图像工具。Hermes 关闭自动 context 文件与 memory；DSH 在 agent 创建时限制工具，并显式禁用自动工作目录 instructions。新版 DSH runner 仅接收已验收的 BC-100，避免旧 data-task 分支重新开放文件/终端；其他 benchmark 需单独完成输入与答案隔离后接入。crop/zoom 仅在每题允许的图片目录内工作，不能用父图代替 crop 做反向搜索。

追加验收通过 localhost 假模型主动请求 `read_file`、`read`、`terminal`、`bash`，要求实际拒绝，并在答案文件与工作目录 `AGENTS.md` 放置唯一标记，检查所有模型请求中均不存在标记；不会读取真实 benchmark 答案进行测试。详情见 [工具隔离验收 JSON](visual-integrity/repair-v3/tool-isolation-validation.json)。本轮 root unittest 104 项通过。
