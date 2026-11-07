# 历史 renderer 的 scale 语义

核对当前自定义 Hermes 源码：`hermes-agent/plugins/context_engine/visual/__init__.py` 与 `render.py`。此解释针对实现语义，不表示历史 Table 5 的参数与数据映射已经确认。

1. `keep_rounds` 默认1：最近一轮保留为原文tail，不参与渲染。head也保留。
2. 对被渲染的历史，`recent_rounds` 默认5：最近五轮采用完整分辨率。
3. 更早的far历史才受 `history_scale` 影响。轮边界由带tool_calls的assistant消息决定，不等同所有message数或API请求数。
4. 当渲染范围不足五轮时，far为空，不同scale可能产生完全相同图像。配置不同不等于实际发生了分辨率干预；分析必须同时报告压缩次数、far段存在/长度和实际图像尺寸/hash。
5. `history_scale=0` 省略far历史图像，并不丢掉所有历史：head、原文tail、recent渲染仍保留。它不能叫作Discard-All。
6. `0<s<1` 时先把far页布局尺寸扩大到约`image_width/s`、`history_height/s`，再对每页做线性缩放s。因此s是线性尺寸缩放参数，不能直接当面积比例、图像token比例或整个上下文压缩比；分页数和每页文本密度同时改变，最终图片宽度可能仍接近基准1024。
7. `s=1` 没有far降采样，但仍将历史渲染为图片，依然不是No Compression。

## 缓存与成本

当前visual引擎在每次压缩时向 `_full_history` 追加内容，并从整个累计历史重新渲染。旧页没有作为不可变canvas冻结，随着recent/far边界移动、排版变化，之前图片与请求前缀可能变化。这是缓存命中率的潜在影响路径，不能单凭代码推断损失大小。

应分别记录供应商cached/non-cache/output tokens，以及工具缓存命中；不能把Serper缓存命中当作LLM prefix缓存命中。`image_tokens_estimate` 属本地启发式估计，不是供应商计费图像token。比较不同scale时需同时报告实际usage、准确率、压缩触发次数和far实际生效比例。缺失计费字段应标未知。

实验6片段pilot采用“同一固定1x画布再降采样”，控制的是像素分辨率；其语义与这里“先扩页、再缩放、仅far受影响”的原引擎策略不同，不能互相冒充。
