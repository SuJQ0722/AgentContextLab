# Text-only Rendering：实现审计与附录说明

审计对象是当前工作树的 Hermes 实现（基准 commit `07a1d56ff9c1812fd6751f5c696bdcea4800b0ca`），不是历史运行配置的推断。没有调用付费 API，也没有修改正在运行实验的 harness。当前 renderer SHA-256 为 `aaf0fe1c5ffc979af0b6ad384215a51f1d888ad2a53407c008bd6edfea31602a`。

**结论：当前 `text_only=True` 表示不渲染图片和表格 flowable；它不自动把每张图生成 caption，也不保证保留表格的文字事实。不能将这个实现直接描述成“所有视觉内容已转换为完整文本，再进行渲染”。**

## Caption 来源和实际 prompt

| 路径 | 谁生成文字 | 模型与 prompt | 源码证据 |
|---|---|---|---|
| `vision_analyze` native fast path | 工具仅返回固定说明和图像；主模型随后可自行分析 | 主会话模型；没有单独的 caption 模型调用 | [分流条件](../../hermes-agent/tools/vision_tools.py#L717)、[工具返回内容](../../hermes-agent/tools/vision_tools.py#L747)、[handler](../../hermes-agent/tools/vision_tools.py#L1350) |
| `vision_analyze` auxiliary path | 辅助视觉模型返回分析文字 | 优先显式 `AUXILIARY_VISION_MODEL`，否则由 `auxiliary.vision` 配置及运行时 provider/router 决定，不能据主模型名断言辅助模型相同 | [handler/prompt](../../hermes-agent/tools/vision_tools.py#L1355)、[调用参数](../../hermes-agent/tools/vision_tools.py#L1063)、[模型解析](../../hermes-agent/agent/auxiliary_client.py#L4769) |
| `image_crop` / `image_zoom_in` | 工具生成坐标、尺寸等元数据说明；不生成图像内容描述 | 无 caption 模型，也无 caption prompt | [crop](../../hermes-agent/tools/image_crop_tool.py#L175)、[zoom](../../hermes-agent/tools/image_zoom_in_tool.py#L260) |
| `image_search` 标题 | 搜索服务返回的标题等元数据 | 不是本地 VLM 生成的 caption | [结果字段](../../hermes-agent/tools/image_search_tool.py#L222)、[文本整理](../../hermes-agent/tools/image_search_tool.py#L246) |
| `text_only` 渲染开关 | 保留原有文字，删除图像/表格渲染对象 | 不调用任何 caption 模型 | [开关实现](../../hermes-agent/plugins/context_engine/visual/render.py#L681) |

Auxiliary 分支的实际完整模板为：

```text
Fully describe and explain everything about this image, then answer the following question:

{question}
```

其中 `{question}` 来自 agent 发出的 `vision_analyze` 工具参数，不是固定的数据集 caption 问题。当前调用将该文字和图像放在一个 user multimodal message 中；`max_tokens=2000`，temperature 默认 0.1，可由 `auxiliary.vision.temperature` 覆盖。该分支没有在这段调用中额外增加 system prompt。

Native 分支返回的实际文字为：

```text
Image loaded into your context — you can see it natively now. Use your built-in vision to answer the user.

Question: {question}
```

问题为空时不追加 `Question` 部分。这段文字不是对图像内容的描述。若后续压缩丢弃图像，只留下此说明，不等于保留了语义 caption。

**历史适用范围：** 上述是当前代码的可验证行为。历史归档可能使用不同版本、不同 `auxiliary.vision` 设置，或走 native/aux 不同分支。若历史轨迹没有保存请求、最终解析模型和配置快照，caption 的实际生成模型应写 `unknown`，不能统一填写 Gemini 或 DeepSeek。附录发布前，应对各历史 campaign 核对这些快照。

## Crop、zoom 和图像如何变成文本

Crop 返回 PNG data URL，以及 `Cropped region (...bbox=...): ... source, ... output.` 这样的尺寸说明。Zoom 返回 PNG data URL、bbox、可选 agent 提供的 label 和超分辨率后端/尺寸说明。两者均不进行 OCR 或语义 caption。

`_format_message_block` 对 list 内容只拼接 `type=text` 的部分，见 [render.py:349](../../hermes-agent/plugins/context_engine/visual/render.py#L349)。因此 text-only 条件可保留坐标、尺寸、原有 agent 分析等文字，但不能据此认为 crop 内的小字、数字、实体或布局已转成文字。

另一个独立限制是当前 [`_extract_images_from_msg`](../../hermes-agent/plugins/context_engine/visual/render.py#L117) 每条最多提取两张图，并排除直接 data URL；它还会尝试从工具调用参数获取 URL/path。因而“完整 visual renderer 原样保留了所有 crop 像素”也不能仅凭策略名断言。实验 3 的 Native Images 控制应对实际原始 image blocks 做独立的哈希/尺寸/数量核对，不能依赖这一抽取函数。

## 表格信息丢失：已离线复现

[`_format_message_block`](../../hermes-agent/plugins/context_engine/visual/render.py#L382) 对 `execute_code`/`terminal` 且参数或内容带数据文件扩展名的输出检测表格。检测成功后把表格放入 `table_data`，并从 `body` 剥除表格文字，常替换为 `[table]`。随后 [`text_only` 分支](../../hermes-agent/plugins/context_engine/visual/render.py#L681) 将 `table_data` 置空，未将单元格文字写回 body。

使用实际 formatter 和实际 PDF renderer，对同一个合成工具输出做了离线验证：

```text
| item | amount |
| --- | --- |
| AUDIT_FACT_Q | 731942 |
```

| 条件 | PDF 可提取文本中的 731942 | 判定 |
|---|---|---|
| visual (`text_only=False`) | 存在 | 数值保留 |
| text-only (`text_only=True`) | 不存在，仅留下 `[table]` | 数值丢失 |

复现命令（使用已安装 ReportLab/PyMuPDF 的 Hermes 环境，无网络调用）：

```bash
hermes-agent/.venv/bin/python scripts/audit_text_only_rendering.py
```

输出：`outputs/experiment3/text-only-audit/audit.json`、`visual.pdf`、`text-only.pdf`。这是当前实现的反例证据，不能反推历史每个失败 case 都由此造成。

此外，当前表格检测/绘制也有行数及单元格截断限制，见 [检测](../../hermes-agent/plugins/context_engine/visual/render.py#L239) 和 [绘制](../../hermes-agent/plugins/context_engine/visual/render.py#L514)；完整 visual 也不是无损编码。

## 可用于附录的准确表述

> 在已审计的实现中，Text-only Rendering 仅渲染轨迹中已有的文字，不对所有视觉证据自动生成 caption。`vision_analyze` 的辅助路径使用上述 prompt 生成文字分析，而 native 路径直接返回图像。Crop/zoom 工具提供像素及几何元数据，不自动转写内容。我们发现当前 text-only 表格路径会在剥离表格文字后禁用表格渲染，因此该版本不能被视作信息完整的文本化对照；历史运行的适用性需结合代码与配置快照核实。

在修正/重新定义此 ablation 之前，不应用它单独支撑“视觉渲染优于充分文本化”的结论。受控 baseline 需要另外保证：原生图像完全一致、表格文字可追踪、图像/文本预算分开核对；新修正版本必须使用新实验标识，不能覆盖旧轨迹。
