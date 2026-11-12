# 视觉上下文增长、session search 与五图上限（2026-11-12）

> 后续更新：本页五图版本已由 [history≤5 / recent≤2](history5-recent2-2026-11-12.md) 取代；下文五图内容保留为修改历史。

本次只做代码审计、离线日志分析、配置修改与本地测试；所有实验继续停止，没有新增模型调用或评分。新五图版本尚未部署或测量，不能用历史十图结果声称其性能。

## 当前实现与 recent 的含义

共享策略默认 `keep_rounds=1`、`recent_rounds=5`。轮次按 assistant tool_calls 边界划分，不是固定消息数。

1. 保护系统/任务头部；最新一个工具轮次保留为原始消息，包含其中的原生图，不渲染成 recent canvas。
2. 对其余待压缩历史，将新消息追加到 `_full_history`。默认 `_max_history_rounds=0` 表示不限制累计历史。每次压缩重新渲染这份累计原文；不会把上一轮栅格图再次套娃渲染。
3. 累计历史中最近五个工具轮次归 recent，以 1.0× 渲染；较早部分归 history，当前 bounded 默认 0.75×。不是 0.75 的逐龄递乘。
4. 当前 bounded renderer 把 recent 和 history 分别排版为多页 PDF，再逐页栅格化；默认页宽 1024、高度上限 2048、16pt/72dpi。`fit_to_content_height=False`，不会把整个 recent 拼成一张无限长图。recent 可以有多页；history 页再一次性缩至 768×1536（原页为1024×2048时）。
5. 页按 history→recent 顺序加入压缩消息；保护头尾的原生图也会进入最终请求。最终图数限制是在传输前执行，不限制后台生成页数。

源码：`scripts/shared_context_policy.py`、`hermes-agent/plugins/context_engine/visual/__init__.py`、`scripts/bounded_multimodal_renderer_v1.py`、`scripts/rq3_bounded_renderer_v2.py`。以上说明针对当前 bounded 运行路径。原生旧版 `render.py` 的 recent 确实试图生成一张大图：页面高度设为 `max_image_height * recent_round_count`，使用 `fit_to_content_height=True`，溢出多页后还会 `_merge_images_vertical` 拼接。该旧函数仍在源码中，但当前上述恢复入口通过 bounded installer 替换它；不能把未安装适配器的旧入口也视为已分页。

## 离线证据与 image token 估计

具体轨迹及完整表见 [compression-growth-2026-11-12.md](compression-growth-2026-11-12.md)。示例按记录压缩次数最多选择，不代表平均轨迹。

BC q048/repeat1 的同一尝试连续六次压缩：消息20→28→32→37→45→57；生成页8→11→16→20→22→27。十图版本最后仅保留10页，丢17页。MMBC样本844条wire图记录中21条发生丢图，均涉及移除原生图；这些是请求记录而非独立题。原生图可能已在canvas中出现，不能从移除事件直接推断证据彻底消失，也不能声称原生图全部原样保留。

代码估计公式 `4 * ceil(width/28) * ceil(height/28)` 是几何启发式，并非已验证的DeepSeek/Gemini计费tokenizer：

| 单页尺寸 | 单页估计 | 5页估计 | 10页估计 |
|---|---:|---:|---:|
|1024×2048|10,952|54,760|109,520|
|768×1536（0.75×）|6,160|30,800|61,600|
|512×1024（0.5×）|2,812|14,060|28,120|

以上不能直接计费。所查两个实验单元仅29次物理请求返回独立image_tokens字段（13次正值、16次0）；无法重建完整实测image-token增长曲线。其他请求缺字段不等于0。Gemini媒体分辨率有模型专属token设置，参见[官方文档](https://ai.google.dev/gemini-api/docs/media-resolution)。

在每轮新增信息与排版密度近似固定、不截断的假设下，单次图像输入随历史长度线性增长；反复发送累计历史的session总输入可能为O(T²)。固定0.75×只降低常数；几何估算的面积系数约0.5625。固定图数限制可以截断发送增长，但不限制累计历史与全量重渲染工作，也不保证可恢复旧证据。

不能把这些复杂度结论当作已测延迟，更不能把所有超时归因于VLM固有特性。此前传输审计发现本地300秒截止与大请求体相关问题；请求字节数、图像token、渲染时间与供应商内部处理时间必须分别记录。

## 本次已实现的五图配置

`configs/experiment.json:visual_image_retention` 是新默认：`visual-recent-five-v1`，每次请求最多5个image_url块，原生图与canvas合计。保持原有顺序，保留最后5张；没有新合并、重编码、上图床或改变分辨率。

- Hermes视觉恢复入口（BC、MMBC VERA/vanilla及RQ3共用入口）显式传入该上限。
- DSH视觉恢复入口把相同上限传给本地Python bridge，复用相同选择实现。
- 最终wire记录版本 `inline-recent-5-chunked-v2`、max_images、保留/移除的来源与哈希。拒绝记录也标明该版本。
- 通用transport默认仍为10，以免改变非视觉baseline与独立受控/信息损失协议。后两者的证据匹配规则不能用此粗裁剪静默替换。
- 独立实验config中的 `visual_image_retention` 优先于根默认；新的冻结配置应复制该段。旧source checkout加旧冻结配置才构成历史复现。新代码下恢复必须新建协议/输出代次，不直接追加到旧成功结果。
- 旧配置中十图transport标识仍是旧worker校验的兼容入口；最终真实cap以新增策略和wire账本为准。冻结新任务时必须将两层区别一并写入manifest。

减少到5图预期降低超过5图请求的负载，但不是实测速度承诺，也不是image-token严格减半。近期内容多时可能只剩recent末尾页；保护头部和原生图仍可能被最终顺序截断。此修改不实现增量渲染、语义选择或长期检索。

## 后续设计建议（尚未实现）

图片不宜成为唯一检索索引。保存原始文本、短摘要、session/turn/URL/实体/数字索引，以及原生图和canvas的稳定定位；检索返回精确原文与必要视觉证据。原文已存在时不必OCR自己的渲染文本。

优先顺序：增量生成且冻结旧页并复用编码；同时约束token/字节/图数；按任务相关性、重要性和重复度选择历史块；移出上下文的内容进入可检索归档；数字URL优先原文，图形布局按需取图或高清crop。冻结页但始终全发仍会增长；缓存命中还取决于前缀和供应商实现。

这是新的记忆策略，应作为独立变体评估，而非把现有结果改名。视觉检索已有相关工作，例如[OCR-Memory](https://arxiv.org/abs/2604.26622)使用视觉标识定位并恢复相关文本；混合检索架构本身不应宣称为新颖贡献。

## 验证

`python -m unittest discover -s tests -v`：1049项通过（2026-11-12）。新增回归覆盖五图按顺序选择、原生图/canvas删除审计、文本和工具字段及图片字节不变、非视觉默认十图兼容、非法上限拒绝，以及DSH bridge与Hermes传输结果一致。现有DSH完整wrapper测试验证上限5传入运行环境与协议账本。本次没有修改harness源码或submodule pin。
